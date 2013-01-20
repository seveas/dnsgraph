# Create your views here.

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
import beanstalkc

class DnsNameForm(ModelForm):
    valid_hostname = re.compile(r'^[-_a-z0-9]+(?:\.[-_a-z0-9]+)+$')

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

def index(request):
    if request.POST:
        form = DnsNameForm(request.POST)
        if form.is_valid():
            obj, created = DnsName.objects.get_or_create(name=form.cleaned_data['name'],
                                                         qtype=form.cleaned_data['qtype'])
            if created:
                obj.queue()
            if obj.available and obj.queried_at and obj.queried_at < datetime.datetime.now() - datetime.timedelta(0,3600):
                obj.available = 0
                obj.queue()
                obj.save()
            return HttpResponseRedirect('./%s/' % form.cleaned_data['name'])
    else:
        form = DnsNameForm()

    data = {'form': form}
    try:
        bs = beanstalkc.Connection(**settings.BEANSTALK_SERVER)
        data['jobs'] = bs.stats_tube('dns-graph')['current-jobs-ready']
    except beanstalkc.CommandFailed:
        pass
    return render_to_response("dnsgraph/index.html", context_instance=RequestContext(request, data))

def by_name(request, name):
    queries = DnsName.objects.filter(name=name)
    if not len(queries):
        raise Http404
    zones = set('.')
    has_results = False
    is_waiting = False
    for query in queries:
        if query.available:
            with open(query.data_path) as fd:
                data = yaml.load(fd)
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
    for qtype_ in recordtypes:
        if request.GET.get('show_%s' % qtype_, None):
            qtype = qtype_
    try:
        query = DnsName.objects.get(name=name, qtype=qtype)
    except DnsName.DoesNotExist:
        raise Http404
    with open(query.data_path) as fd:
        root = tracegraph.Zone.load('yaml', fd)
    skip = [x[5:] for x in request.GET if x.startswith('skip_')]
    graph = root.graph(skip=skip)
    return HttpResponse(shell.dot('-T', 'png', input="\n".join(graph)).stdout, content_type='image/png')
