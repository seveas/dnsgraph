from django.conf.urls import patterns, url

urlpatterns = patterns('dnsgraph.views',
    url(r'^$', 'index'),
    url(r'^(?P<name>.*)/(?P<qtype>.*).png$', 'as_png'),
    url(r'^(?P<name>.*)/(?P<qtype>.*)/$', 'by_name'),
)
