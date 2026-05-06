import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


class ChatClient:
    def __init__(self, host: str, port: int, username: str):
        self.host = host
        self.port = port
        self.username = username
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None

    async def connect(self) -> bool:
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        except Exception as e:
            logger.error("Server error: %s", e)
            return False

        data = await self.reader.readline()
        if not data:
            logger.error("Server closed connection.")
            return False
        self.writer.write((self.username + "\n").encode())
        await self.writer.drain()

        response = await self.reader.readline()
        if not response:
            logger.error("Connection error.")
            return False
        if response and b"already taken" in response:
            logger.error("Имя пользователя '%s' уже существует", self.username)
            self.writer.close()
            return False
        logger.info("Добро пожаловать в чат. Можете начинать общаться (Ctrl+C чтобы выйти):")
        return True

    async def receive_messages(self) -> None:
        try:
            while True:
                data = await self.reader.readline()
                if not data:
                    logger.info("Disconnected from server.")
                    break
                message = data.decode().strip()
                logger.info(message)
                sys.stdout.flush()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def send_messages(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                message = line.strip()
                if not message:
                    continue
                if message.lower() == "/quit":
                    break
                self.writer.write((message + "\n").encode())
                await self.writer.drain()
        except asyncio.CancelledError:
            pass
        finally:
            self.writer.close()

    async def run(self) -> None:
        if not await self.connect():
            return
        tasks = [
            asyncio.create_task(self.receive_messages()),
            asyncio.create_task(self.send_messages()),
        ]
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()


if __name__ == "__main__":
    if len(sys.argv) == 4:
        host, port, username = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    else:
        host = input("Server address [127.0.0.1]: ") or "127.0.0.1"
        port = int(input("Port [8888]: ") or 8888)
        username = input("Имя пользователя: ").strip()
        if not username:
            logger.error("Имя пользователя не может быть пустым.")
            sys.exit(1)

    client = ChatClient(host, port, username)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\nDisconnected.")
