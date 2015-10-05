import datetime
from django.conf import settings
from django.db import models
from azuki import beanstalk
import os
import tracegraph

recordtypes = ("A", "AAAA", "MX", "PTR", "SOA", "SRV", "TXT")

class DnsName(models.Model):
    name = models.CharField("DNS Name", max_length=100)
    qtype = models.CharField("Query Type", max_length=4, choices=[(x, x + ' Record') for x in recordtypes], default='A')
    available = models.BooleanField("Available", default=False, editable=False)
    queried_at = models.DateTimeField("Queried at", blank=True, null=True, editable=False)

    @property
    def data_path(self):
        return os.path.join(settings.STATIC_ROOT, 'dnsgraph', "%s-%s.yaml" % (self.name.replace('.', '_'), self.qtype))

    @beanstalk('dns-graph')
    def trace(self):
        root = tracegraph.root()
        root.trace(self.name, self.qtype)
        with open(self.data_path, 'w') as fd:
            root.dump('yaml', fd)
        self.available = True
        self.queried_at = datetime.datetime.now()
        self.save()
