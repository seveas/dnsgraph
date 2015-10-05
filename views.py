# Create your views here.

import dns.reversename
from django.shortcuts import render_to_response
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
            if created:
                obj.trace()
            if obj.available and ((obj.queried_at and obj.queried_at < datetime.datetime.now() - datetime.timedelta(0,900))
                                  or not os.path.exists(obj.data_path)):
                obj.available = 0
                obj.trace()
                obj.save()
            return HttpResponseRedirect('./%s/' % form.cleaned_data['name'])
    else:
        form = DnsNameForm()

    data = {'form': form}
    data['jobs'] = DnsName.trace.stats()['current-jobs-ready']
    return render_to_response("dnsgraph/index.html", context_instance=RequestContext(request, data))

def by_name(request, name):
    queries = DnsName.objects.filter(name=name)
    if not len(queries):
        raise Http404
    zones = set('.')
    has_results = False
    is_waiting = False
    for query in queries:
        if query.available and ((query.queried_at and query.queried_at < datetime.datetime.now() - datetime.timedelta(0,900)) 
                                or not os.path.exists(query.data_path)):
            query.available = 0
            query.trace()
            query.save()
            is_waiting = True
        elif query.available:
            with open(query.data_path) as fd:
                data = yaml.safe_load(fd)
                zones = zones.union(set([x['name'] for x in data['zones']]))
            has_results = True
        else:
            is_waiting = True

    return render_to_response('dnsgraph/by_name.html', context_instance=RequestContext(request, {
        'queries': queries,
        'zones': sorted(list(zones)),
        'has_results': has_results,
        'is_waiting': is_waiting,
    }))

def as_png(request, name):
    qtype = 'A'
    format = request.GET.get('format', 'png')
    if format not in tracegraph.__dot_formats and format != 'raw':
        format = 'png'
    for qtype_ in recordtypes:
        if request.GET.get('show_%s' % qtype_, None):
            qtype = qtype_
    try:
        query = DnsName.objects.get(name=name, qtype=qtype)
    except DnsName.DoesNotExist:
        raise Http404
    if not os.path.exists(query.data_path):
        raise Http404
    with open(query.data_path) as fd:
        root = tracegraph.Zone.load('yaml', fd)
    skip = [x[5:] for x in request.GET if x.startswith('skip_')]
    graph = root.graph(skip=skip)
    if format == 'raw':
        return HttpResponse("\n".join(graph), content_type='text/plain')
    return HttpResponse(shell.dot('-T', format, input="\n".join(graph)).stdout, content_type='image/png')
