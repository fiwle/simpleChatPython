import sys
import asyncio
import logging
import uuid

# настройка логгирования (префиксы, время и т.д)
logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] [SERVER] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


class FileStorage:
    """
    Хранилище загруженных файлов в оперативной памяти.
    Файлы сохраняются в виде словаря: ключ - сгенерированный ID,
    значение - кортеж (имя_файла, данные).
    """
    def __init__(self):
        self.files: dict[str, tuple] = {}

    def store(self, filename: str, data: bytes) -> str:
        """
        Сохраняет файл и возвращает ID
        :param filename: имя файла
        :param data: бинарные данные файла
        :return: ID файла
        """
        fid = uuid.uuid4().hex[:8]
        self.files[fid] = (filename, data)
        return fid

    def get(self, fid: str) -> tuple:
        """
        Возвращает данные файлы по ID (None, если файл не найден)
        :param fid: ID файла
        :return: tuple(filename, filedata)/None
        """
        return self.files.get(fid)


class ClientSession:
    """
    Представление сессии одного клиента. Хранит потоки ввода и вывода и имя пользователя.
    """
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, name: str):
        """
        :param reader: asyncio.StreamReader для чтения.
        :param writer: asyncio.StreamWriter для записи.
        :param name: имя пользователя в чате (уникальное).
        """
        self.reader = reader
        self.writer = writer
        self.name = name

    async def send(self, message: str) -> None:
        """
        Отправляет сообщение клиенту. При ошибке логгирует предупреждение.
        :param message: текст сообщения
        :return: None
        """
        try:
            self.writer.write((message + "\n").encode())
            await self.writer.drain()
        except Exception:
            logger.warning("Failed to send message to %s", self.name)

    async def send_file(self, filename: str, data: bytes) -> None:
        """
        Отправляет клиенту файл. Сначала имя и размер файла, затем само содержимое файла.
        Вызывается при скачивании файла (/download)
        :param filename: имя файла
        :param data: данные файла
        :return: None
        """
        try:
            header = f"/file {filename} {len(data)}\n"
            self.writer.write(header.encode())
            self.writer.write(data)
            await self.writer.drain()
        except Exception:
            logger.warning("Failed to send file to %s", self.name)


class ChatServer:
    """
    Класс сервера чата.
    Управление подключениями клиентов, рассылкой сообщений, файлами.
    """
    def __init__(self):
        self.clients: dict[str, ClientSession] = {}
        self.files = FileStorage()

    async def broadcast(self, message: str, exclude: str = None) -> None:
        """
        Рассылка сообщения всем клиентам, кроме отправителя.
        :param message: текст сообщения
        :param exclude: имя отправителя
        :return:  None
        """
        tasks = [c.send(message) for n, c in self.clients.items() if n != exclude]
        if tasks:
            await asyncio.gather(*tasks)

    async def handle_private(self, sender_name: str, args: str) -> None:
        """
        Обработка приватных сообщений (/private или @[username]).
        :param sender_name: имя отправителя
        :param args: строка "[username] [message]"
        :return: None
        """
        parts = args.split(" ", 1)
        if len(parts) < 2:
            await self.clients[sender_name].send("Для использования приватных сообщений: /private [name] [message]")
            return
        # target, msg = parts[0], parts[1]
        target, msg = parts
        target_session = self.clients.get(target)
        if target_session is None:
            await self.clients[sender_name].send(f"Пользователь {target} не найден.")
            return
        await target_session.send(f"[Приватно от {sender_name}]: {msg}")
        await self.clients[sender_name].send(f"[Приватно для {target}]: {msg}")

    # async def handle_file_upload(self, sender_name: str, client: ClientSession) -> None:
    #     pass

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """
        Обработчик одного клиента.
        Обработка регистрации имени, приема команд/сообщений, оповещений и отключения.
        :param reader: asyncio.StreamReader - читатель
        :param writer: asyncio.StreamWriter - писатель
        :return: None
        """
        addr = writer.get_extra_info('peername')
        logger.info("New connection from %s", addr)

        # регистрация имени клиента
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

        # проверка уникальности
        if name in self.clients:
            writer.write("Имя пользователя уже занято. Отключение. \n".encode())
            await writer.drain()
            writer.close()
            logger.info("Duplicate name '%s' from %s", name, addr)
            return

        # создание сессии клиента
        client = ClientSession(reader, writer, name)
        self.clients[name] = client
        logger.info("'%s' joined the chat", name)

        # оповещение
        await client.send(f"Добро пожаловать в чат, {name}!")
        await self.broadcast(f"User {name} joined the chat.")

        # обработка сообщений
        try:
            while True:
                data = await reader.readline()
                if not data:  # отключение клиентом
                    break
                message = data.decode().strip()

                # обработка приватного сообщения
                if message.startswith("/private "):
                    args = message[len("/private "):]
                    await self.handle_private(name, args)

                # обработка загрузки файла
                elif message.startswith("/file "):
                    parts = message[len("/file "):].split()
                    if len(parts) != 2:
                        await client.send("Для отправки файлов используйте /file [filename] [size]")
                        continue
                    # filename, size_str = parts[0], parts[1]
                    filename, size_str = parts
                    try:
                        size = int(size_str)
                    except ValueError:
                        await client.send("Неверный размер файла")
                        continue
                    await client.send(f"Файл {filename} ({size} байт) получен сервером.")
                    # получаем нужное количество байт чтобы не возникало ошибок
                    file_data = await reader.readexactly(size)
                    fid = self.files.store(filename, file_data)
                    await self.broadcast(f"File uploaded by {name}: {filename} ({fid})", exclude=name)
                    await client.send(f"Файл успешно загружен под ID: {fid}")

                # обработка скачивания файла
                elif message.startswith("/download "):
                    fid = message[len("/download "):].strip()
                    file_entry = self.files.get(fid)
                    if file_entry is None:
                        await client.send(f"Файл с ID {fid} не найден")
                    else:
                        file_name, file_data = file_entry
                        await client.send_file(file_name, file_data)

                # обработка незвестной команды
                elif message.startswith("/"):
                    await client.send(f"Неизвестная команда: {message}")

                # общие сообщения (или с @)
                else:
                    if message.startswith("@"):
                        if message.find(" ") == -1:
                            await client.send("Неверный формат приватного сообщения, используйте @[username] [message]")
                        else:
                            target = message[1:message.find(" ")]
                            msg = message[message.find(" ")+1:]
                            await self.handle_private(name, f"{target} {msg}")
                    else:
                        await self.broadcast(f"[{name}]: {message}", exclude=name)
        except asyncio.IncompleteReadError:
            pass  # клиент отключился
        except Exception as e:
            logger.error("Error handling client '%s': %s", name, e)
        finally:
            # удаление клиента и оповещение
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
        """
        Запуск сервера на адресе и порте.
        :param host: адрес сервера
        :param port: порт сервера
        :return: None
        """
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
