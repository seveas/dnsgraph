from django.core.management import BaseCommand
from dnsgraph.models import DnsName
from django.db import connection
import beanstalkc
from django.conf import settings
import tracegraph
import datetime

class Command(BaseCommand):
    help = "Run all the DNS requests"

    def handle(self, *args, **options):
        bs = beanstalkc.Connection(**settings.BEANSTALK_SERVER)
        bs.watch('dns-graph')
        while True:
            job = bs.reserve()
            name, qtype = job.body.split()
            print "Processing %s (%s)" % (name, qtype)
            root = tracegraph.root()
            root.trace(name,qtype)
            dn = DnsName.objects.get(name=name, qtype=qtype)
            with open(dn.data_path, 'w') as fd:
                root.dump('yaml', fd)
            dn.available = True
            dn.queried_at = datetime.datetime.now()
            dn.save()
            job.delete()
