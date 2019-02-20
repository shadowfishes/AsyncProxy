import logging
import asyncio
from urllib import parse


logger = logging.getLogger("handle")

SEP_LINE = b"\r\n"
SPACE = b" "

RECV_REQUEST_INIT = 0
RECV_REQUEST_LINE = 5
RECV_REQUEST_HEADER = 10
RECV_REQUEST_HEADER_COMPLETE = 15
RECV_REQUEST_DATA = 20
RECV_REQUEST_COMPLETE = 25

proxy_response = SEP_LINE.join([
            b'HTTP/1.1 200 Connection established',
            b'Proxy-agent: async proxy ',
            SEP_LINE])

bad_response = SEP_LINE.join([
                    b'HTTP/1.1 502 Bad Gateway',
                    b'Proxy-agent: async proxy',
                    b'Content-Length: 11',
                    b'Connection: close',
                    SEP_LINE]) + b'Bad Gateway'


async def handler(reader, writer):
    client_name = writer.get_extra_info("peername")

    async with ProxyServer(reader, writer) as server:
        if await server.handle_request():
            await server.exchange_data()

    logger.info("connection to {} is shutdown by proxyserver".format(client_name))


class ProxyServer:
    def __init__(self, c_reader, c_writer, s_reader=None, s_writer=None):
        self.c_reader = c_reader
        self.c_writer = c_writer
        self.s_reader = s_reader
        self.s_writer = s_writer
        self.request = dict()
        self.raw_data = b""
        self.state = RECV_REQUEST_INIT
        self.event = asyncio.Event()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            logger.exception(exc_val)
        if self.s_writer:
            self.s_writer.close()
            await self.s_writer.wait_closed()
        self.c_writer.close()
        await self.c_writer.wait_closed()
        self.closed = True
        return True

    async def handle_request(self):
        if not await self.recv_request():
            logger.info("bad request from {}, close connections".format(self.c_writer.get_extra_info("peername")))
            if self.raw_data:
                print(self.raw_data)
            self.c_writer.write(bad_response)
            await self.c_writer.drain()
            self.c_writer.close()
            await self.c_writer.wait_closed()
            return False

        url, port = self.parse_url()
        if not url or not port:
            logger.info("error while parsing url")
            return False

        logger.info("waiting for connect to {}:{}".format(url, port))
        task = asyncio.create_task(asyncio.open_connection(url, eval(port)))
        done, pending = await asyncio.wait([task, ], timeout=10, return_when=asyncio.FIRST_COMPLETED)
        if task not in done:
            logger.debug("timeout while connecting to {}".format(url))
            task.cancel()
            return False
        else:
            logger.debug("{} successly conneted to {}".format(self.c_writer.get_extra_info("peername"), url))
            self.s_reader, self.s_writer = task.result()

        if self.request[b"method"] == b"CONNECT":
            self.c_writer.write(proxy_response)
            await self.c_writer.drain()
        else:
            self.s_writer.write(self.raw_data)
            await self.s_writer.drain()
        return True

    async def recv_request(self):
        cache = b""
        self.raw_data = b""
        self.state = RECV_REQUEST_INIT
        while True:
            logger.debug("waiting {} for request:".format(self.c_writer.get_extra_info("peername")))
            data = await self.c_reader.read(8192)
            if not data:
                return None
            self.raw_data += data
            cache += data
            try:
                cache = await self.parse_request(cache)
            except Exception as err:
                logger.exception(err)
                return None
            if self.state == RECV_REQUEST_COMPLETE:
                break
        return True

    async def parse_request(self, cache):
        while True:
            # 切一行进行处理
            line, cache = split_line(cache)
            if line:
                self.parse_line(line)

            # 数据不够一行俩进行处理
            elif line is None:
                if self.state >= RECV_REQUEST_HEADER_COMPLETE and self.request[b"method"] == b"POST":
                    if self.state == RECV_REQUEST_HEADER_COMPLETE:
                        self.state = RECV_REQUEST_DATA
                        self.request[b"body"] = cache
                    if self.state == RECV_REQUEST_DATA:
                        self.request[b"body"] += cache
                    if eval(self.request[b"Content-Length"]) <= len(self.request[b"body"]):
                        self.state = RECV_REQUEST_COMPLETE
                    return b""
                return cache

            # 数据为一个空行
            else:
                if self.state == RECV_REQUEST_HEADER and self.request[b"method"] != b"POST":
                    self.state = RECV_REQUEST_COMPLETE
                else:
                    self.state = RECV_REQUEST_HEADER_COMPLETE
                return cache

    def parse_line(self, line):
        if self.state <= RECV_REQUEST_LINE:
            method, url, version = line.split(SPACE)
            self.request[b"method"] = method
            self.request[b"url"] = url
            self.request[b"version"] = version
            self.state = RECV_REQUEST_HEADER
        if self.state == RECV_REQUEST_HEADER:
            k, v = line.split(b":", 1)
            self.request[k] = v.strip(SPACE)
        return

    async def exchange_data(self):
        self.event.set()
        send_to_server = asyncio.create_task(send_data(self.c_reader, self.s_writer, self.event))
        send_to_client = asyncio.create_task(send_data(self.s_reader, self.c_writer, self.event))
        done, pending = await asyncio.wait([send_to_client, send_to_server], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    def parse_url(self):
        url = self.request.get(b"Host", None) or self.request[b"url"]
        if not url:
            logger.info("request error")
            return None, None
        res = parse.urlparse(url)
        url = res.netloc or res.path
        url = url.decode()
        if ":" in url:
            return url.split(":")
        else:
            return url, "80"


def split_line(data):
    index = data.find(SEP_LINE)
    if index == -1:
        return None, data
    line = data[0:index]
    data = data[index + len(SEP_LINE):]
    return line, data


async def send_data(reader, writer, event=None):
    while True:
        if event:
            await event.wait()
        try:
            data = await reader.read(8192)
        except ConnectionResetError as err:
            event.clear()
            logger.exception(err)
            return True
        if not data:
            event.clear()
            logger.info("send data to {} completed".format(writer.get_extra_info("peername")))
            break
        writer.write(data)
        await writer.drain()










