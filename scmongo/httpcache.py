from time import time

from scrapy.responsetypes import responsetypes
from scrapy import conf
from scrapy.utils.request import request_fingerprint
from scrapy.http import Headers

from gridfs import GridFS, errors

from scmongo.util import get_database


class MongoCacheStorage(object):
    """Storage backend for Scrapy HTTP cache, which stores responses in MongoDB
    GridFS
    """

    def __init__(self, settings=conf.settings):
        self.expire = settings.getint('HTTPCACHE_EXPIRATION_SECS')
        self.compression = self._get_compression_algorithm(settings)
        self.db = get_database(settings)
        self.fs = {}

    def open_spider(self, spider):
        self.fs[spider] = GridFS(self.db, 'httpcache')

    def close_spider(self, spider):
        del self.fs[spider]

    def retrieve_response(self, spider, request):
        gf = self._get_file(spider, request)
        if gf is None:
            return # not cached
        url = str(gf.url)
        status = str(gf.status)
        headers = Headers([(x, map(str, y)) for x, y in gf.headers.iteritems()])
        compression = gf._file.get('compression')
        body = self._decompress(gf.read(), compression)
        respcls = responsetypes.from_args(headers=headers, url=url)
        response = respcls(url=url, headers=headers, status=status, body=body)
        return response
 
    def store_response(self, spider, request, response):
        key = spider.name + '/' + self._request_key(request)
        kwargs = {
            '_id': key,
            'time': time(),
            'status': response.status,
            'url': response.url,
            'headers': dict(response.headers),
            'compression': self.compression,
        }
        body = self._compress(response.body)
        try:
            self.fs[spider].put(body, **kwargs)
        except errors.FileExists:
            self.fs[spider].delete(key)
            self.fs[spider].put(body, **kwargs)

    def _get_file(self, spider, request):
        key = spider.name + '/' + self._request_key(request)
        try:
            gf = self.fs[spider].get(key)
        except errors.NoFile:
            return # not found
        if 0 < self.expire < time() - gf.time:
            return # expired
        return gf

    def _request_key(self, request):
        return request_fingerprint(request)

    def _get_compression_algorithm(self, settings):
        compression_algorithm = settings.get('HTTPCACHE_COMPRESSION')
        if not (compression_algorithm == 'zlib' or compression_algorithm is None):
            raise ValueError("Compression algorithm %s not supported" % compression_algorithm)
        return compression_algorithm

    def _compress(self, response_body):
        if (self.compression == 'zlib'):
            return response_body.encode('zlib')
        return response_body

    def _decompress(self, compressed_body, compression):
        if compression == 'zlib':
            return compressed_body.decode('zlib')
        return compressed_body
