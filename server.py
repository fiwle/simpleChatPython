import sys
import asyncio
import logging

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] [SERVER] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


class ClientSession:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, name: str):
        self.reader = reader
        self.writer = writer
        self.name = name

    async def send(self, message: str) -> None:
        try:
            self.writer.write((message + "\n").encode())
            await self.writer.drain()
        except Exception:
            logger.warning("Failed to send message to %s", self.name)


class ChatServer:
    def __init__(self):
        self.clients: dict[str, ClientSession] = {}

    async def broadcast(self, message: str, exclude: str = None) -> None:
        tasks = []
        for name, client in self.clients.items():
            if name != exclude:
                tasks.append(client.send(message))
        if tasks:
            await asyncio.gather(*tasks)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info('peername')
        logger.info("New connection from %s", addr)

        try:
            writer.write("Введите Ваше имя пользователя: \n".encode())
            await writer.drain()
            name_line = await reader.readline()
            if not name_line:
                writer.close()
                return
            name = name_line.decode().strip()
        except Exception:
            writer.close()
            return

        if name in self.clients:
            writer.write("Имя пользователя уже занято. Отключение. \n".encode())
            await writer.drain()
            writer.close()
            logger.info("Duplicate name '%s' from %s", name, addr)
            return

        client = ClientSession(reader, writer, name)
        self.clients[name] = client
        logger.info("'%s' joined the chat", name)

        await client.send(f"Добро пожаловать в чат, {name}!")
        await self.broadcast(f"User {name} joined the chat.")

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                message = data.decode().strip()
                if not message:
                    continue
                await self.broadcast(f"[{name}]: {message}", exclude=name)
        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            logger.error("Error handling client '%s': %s", name, e)
        finally:
            if name in self.clients:
                del self.clients[name]
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            await self.broadcast(f"User {name} left the chat.")
            logger.info("'%s' disconnected", name)

    async def start(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        server = await asyncio.start_server(self.handle_client, host, port)
        logger.info("Server started on %s:%d", host, port)
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8888
    chat = ChatServer()
    try:
        asyncio.run(chat.start(host, port))
    except KeyboardInterrupt:
        logger.info("Server stopped.")
