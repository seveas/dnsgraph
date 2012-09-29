from django.conf.urls.defaults import patterns, include, url

urlpatterns = patterns('dnsgraph.views',
    url(r'^$', 'index'),
    url(r'^png/(?P<name>.*)/$', 'as_png'),
    url(r'^(?P<name>.*)/$', 'by_name'),
)
