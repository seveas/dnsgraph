from django.conf import settings
from django.db import models
import beanstalkc
import os

recordtypes = ("A", "AAAA", "MX", "SRV", "TXT")

class DnsName(models.Model):
    name = models.CharField("DNS Name", max_length=100)
    qtype = models.CharField("Query Type", max_length=4, choices=[(x, x + ' Record') for x in recordtypes], default='A')
    available = models.BooleanField("Available", default=False, editable=False)
    queried_at = models.DateTimeField("Queried at", blank=True, null=True, editable=False)

    def queue(self):
        bs = beanstalkc.Connection(**settings.BEANSTALK_SERVER)
        bs.use('dns-graph')
        bs.put(str("%s %s" % (self.name,self.qtype)))

    @property
    def data_path(self):
        return os.path.join(settings.STATIC_ROOT, 'dnsgraph', "%s-%s.yaml" % (self.name.replace('.', '_'), self.qtype))
