import ssl
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager

class TLSAdapter(HTTPAdapter):
	def __init__(self, tls_version=None, **kwargs):
		self.tls_version = tls_version
		super(TLSAdapter, self).__init__(**kwargs)

	def init_poolmanager(self, connections, maxsize, block=False):
		self.poolmanager = PoolManager(
			num_pools = connections,
			maxsize = maxsize,
			block = block,
			ssl_version = self.tls_version
		)
