import logging
import argparse
import asyncio
import sys


from handle import handler


parser = argparse.ArgumentParser()
parser.add_argument("--msg", default="DEBUG", help="set infomation level, default:INFO")
args = parser.parse_args()

info_level = r"logging."+args.msg

logger = logging.getLogger("main")
logging.basicConfig(level=eval(info_level), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


async def main():
    # server = await asyncio.start_server(handler, "172.19.113.87", 2222, start_serving=False)
    server = await asyncio.start_server(handler, "localhost", 8899, start_serving=False)
    async with server:
        logger.info("server running")
        await server.serve_forever()


if __name__ == "__main__":
    try:
        if not sys.version.startswith("3.7"):
            raise Exception("only support by py3.7 or higher")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("server canceled by keyboard")
    except Exception as err:
        logger.info(err)
        logger.info("server exit by exception")
