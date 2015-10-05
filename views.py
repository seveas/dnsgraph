# Create your views here.

import dns.reversename
from django.shortcuts import render_to_response, get_object_or_404
from django.forms import ModelForm, TextInput, ValidationError
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import RequestContext
from dnsgraph.models import DnsName, recordtypes
from django.conf import settings
import re
import yaml
import tracegraph
from whelk import shell
import datetime
import os

class DnsNameForm(ModelForm):
    # Not quite true, but good enough
    valid_hostname = re.compile(r'^[-_a-z0-9]+(?:(:?\.|:+)[-_a-z0-9]+)+$')

    class Meta:
        model = DnsName
        widgets = {
            'name': TextInput(attrs={'placeholder': "Enter hostname to trace"}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].lower()
        if not self.valid_hostname.match(name):
            raise ValidationError("Invalid hostname")
        return name

    def clean(self):
        cleaned_data = super(DnsNameForm, self).clean()
        if 'name' in cleaned_data:
            if cleaned_data['qtype'] == 'PTR':
                try:
                    cleaned_data['name'] = dns.reversename.from_address(cleaned_data['name']).to_text()
                except dns.exception.SyntaxError:
                    pass
        return cleaned_data

def index(request):
    if request.POST:
        form = DnsNameForm(request.POST)
        if form.is_valid():
            obj, created = DnsName.objects.get_or_create(name=form.cleaned_data['name'],
                                                         qtype=form.cleaned_data['qtype'])
            obj.maybe_trace()
            return HttpResponseRedirect('./%s/%s/' % (form.cleaned_data['name'], form.cleaned_data['qtype']))
    else:
        form = DnsNameForm()

    return render_to_response("dnsgraph/index.html", context_instance=RequestContext(request, {
        'form': form,
        'jobs': DnsName.trace.stats()['current-jobs-ready'],
    }))

def by_name(request, name, qtype):
    query = get_object_or_404(DnsName, name=name, qtype=qtype)
    query.maybe_trace()
    zones = set('.')

    if query.available:
        with open(query.data_path) as fd:
            data = yaml.safe_load(fd)
            zones = zones.union(set([x['name'] for x in data['zones']]))

    return render_to_response('dnsgraph/by_name.html', context_instance=RequestContext(request, {
        'query': query,
        'zones': sorted(list(zones)),
        'jobs': DnsName.trace.stats()['current-jobs-ready'],
    }))

def as_png(request, name, qtype):
    format = request.GET.get('format', 'png')
    if format not in tracegraph.__dot_formats and format != 'raw':
        format = 'png'
    query = get_object_or_404(DnsName, name=name, qtype=qtype)
    if not os.path.exists(query.data_path):
        query.trace()
        return HttpResponseRedirect('./%s/' % qtype)
    with open(query.data_path) as fd:
        root = tracegraph.Zone.load('yaml', fd)
    skip = [x[5:] for x in request.GET if x.startswith('skip_')]
    graph = root.graph(skip=skip)
    if format == 'raw':
        return HttpResponse("\n".join(graph), content_type='text/plain')
    return HttpResponse(shell.dot('-T', format, input="\n".join(graph)).stdout, content_type='image/png')
