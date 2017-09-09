import logging
from datetime import datetime

from .models import Proxy, AbstractProxyProcessor


logger = logging.getLogger(__name__)


CHECK_URLS = {
    'http': 'http://httpbin.org/get?show_env=1',
    'https': 'https://httpbin.org/get?show_env=1',
}


class ProxyChecker(AbstractProxyProcessor):
    def __init__(self, proxy=None, pool=None, pool_size=None,
                 session=None, timeout=5, max_retries=0, retry_timeout=0,
                 http_check=True, https_check=True, https_force_check=False):
        super().__init__(proxy, pool, pool_size)

        self.timeout = timeout
        # TODO: not implemented
        self.max_retries = max_retries
        self.retry_timeout = retry_timeout

        self.http_check = http_check
        self.https_check = https_check
        # Checks even if only http is supported
        # Needed for some fetchers that not reporting that proxy supports https
        self.https_force_check = https_force_check

    def __call__(self, *proxies, join=False):
        for proxy in proxies:
            self.spawn(self.worker, proxy)
        if join:
            self.workers.join()

    def create_session(self):
        # Lazy import requests because of gevent.monkey_patch
        from .requests import ConfigurableSession, ForgetfulCookieJar
        return ConfigurableSession(cookies=ForgetfulCookieJar(), timeout=self.timeout)

    def worker(self, proxy):
        # Creating session each time not to hit [Errno 24] Too many open files
        session = self.create_session()
        https_support = proxy.types.intersection([Proxy.TYPE.HTTPS, Proxy.TYPE.SOCKS4,
                                                  Proxy.TYPE.SOCKS5])

        success = None
        if ((self.https_check and https_support) or self.https_force_check):
            success = self.check(session, 'https', proxy)
            if proxy.parsed.scheme.startswith('http'):
                if success:
                    proxy.types.add(Proxy.TYPE.HTTPS)
                elif Proxy.TYPE.HTTPS in proxy.types:
                    proxy.types.remove(Proxy.TYPE.HTTPS)

        # Assuming that if we have https working, http working also
        # TODO: we can't test anonymity then
        if (self.http_check and success is None):
            success = self.check(session, 'http', proxy)

        # TODO: maybe add logging that proxy is skipped?
        # don't make this an error? Сынк эбаут ит!
        assert success is not None, 'proxy not checked'
        self.process_proxy(proxy)

    def check(self, session, protocol, proxy):
        proxies = {'http': proxy.url, 'https': proxy.url}
        try:
            resp = session.get(CHECK_URLS[protocol], proxies=proxies)
            resp.raise_for_status()
            assert 'origin' in resp.json()
            # TODO: anonymity check for http
            # TODO: speed check
        except Exception as exc:
            proxy.fail_at = datetime.utcnow()
            proxy.fail += 1
            logging.debug(f'Check {protocol} fail: {proxy.url}: {exc}')
            return False
        else:
            logging.debug(f'Check {protocol} success: {proxy.url}')
            proxy.success_at = datetime.utcnow()
            proxy.fail_at = None
            proxy.fail = 0
            if proxy.parsed.scheme.startswith('http'):
                proxy.types.add(Proxy.TYPE.HTTPS)
            return True


# TODO: add cli
# def main():
#     from .utils import gevent_monkey_patch
#     gevent_monkey_patch()
#     import pickle
#
#     proxies = pickle.load(open('proxies', 'rb'))
#     checker = ProxyChecker()
#     checker([p for p in proxies if p.TYPE.HTTP in p.types], join=True)
