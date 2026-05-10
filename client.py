import asyncio
import sys
import logging
import os
from pathlib import Path

# настройка логирования
logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


class ChatClient:
    """
    Клиент чата.
    Соединение, отправка и получение сообщений.
    """
    def __init__(self, host: str, port: int, username: str):
        """
        Инициализирует параметры подключения и создает папку для скачанных файлов.
        :param host: адрес сервера
        :param port: порт сервера
        :param username: имя пользователя
        """
        self.host = host
        self.port = port
        self.username = username
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self.downloads_dir = Path("downloads")
        self.downloads_dir.mkdir(exist_ok=True)  # создать папку если ее нет

    async def connect(self) -> bool:
        """
        Устанавливает соединение с сервером и регистрирует имя пользователя
        :return: True, если регистрация и подключение успешны, иначе False.
        """
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
        """
        Асинхронно читает сообщения от сервера.
        Обрабатывает обычные сообщения и заголовки файлов. При получении файла сохраняет в папку.
        :return: None
        """
        try:
            while True:
                data = await self.reader.readline()
                if not data:
                    logger.info("Disconnected from server.")
                    break
                message = data.decode().strip()

                if message.startswith("/file "):
                    parts = message[len("/file "):].split(maxsplit=1)
                    if len(parts) != 2:
                        print(f"\r[ERROR] Ошибка в заголовке файла\n", end="")
                        continue
                    # file_name, size_str = parts[0], parts[1]
                    file_name, size_str = parts
                    try:
                        size = int(size_str)
                    except ValueError:
                        print(f"\r[ERROR] Неверный размер файла: {size_str}\n", end="")
                        continue
                    print(f"\r[Загрузка] {file_name} ({size} байт)....\n", end="")
                    try:
                        file_data = await self.reader.readexactly(size)
                        file_path = self.downloads_dir / file_name
                        # если файл с таким именем есть, то добавляем суффикс _[counter] чтобы избегать ошибок
                        counter = 1
                        while file_path.exists():
                            stm, ext = os.path.splitext(file_name)
                            file_path = self.downloads_dir / f"{stm}_{counter}{ext}"
                            counter += 1
                        file_path.write_bytes(file_data)
                        print(f"\r[Загружено] Файл сохранен в {file_path}\n", end="")
                        sys.stdout.flush()
                    except asyncio.IncompleteReadError:
                        print(f"\r[ERROR] Загрузка не была завершена успешно\n", end="")
                else:
                    print(f"\r{message}\n", end="")
                sys.stdout.flush()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Получена ошибка: %s", e)

    async def send_messages(self) -> None:
        """
        Асинхронно отправляет сообщения пользователя.
        Распознает команды и реализует их поведение.
        :return: None
        """
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
                elif message.lower() == "/help":
                    print("Комманды: @[username] [message], /file [path], /download [id], /quit")
                    continue
                elif message.startswith("/file "):
                    file_path = message[len("/file "):].strip()
                    if not os.path.isfile(file_path):
                        print(f"\r[ERROR] Файл не найден: {file_path}")
                        continue
                    try:
                        file_data = Path(file_path).read_bytes()
                        file_name = os.path.basename(file_path)
                        size = len(file_data)
                        header = f"/file {file_name} {size}\n"
                        self.writer.write(header.encode())
                        self.writer.write(file_data)
                        await self.writer.drain()
                        print(f"[Загрузка] {file_name} ({size} байт)....")
                    except Exception as e:
                        print(f"\r[ERROR] Ошибка при чтении/загрузке файла: {e}")
                    continue
                else:
                    self.writer.write((message + "\n").encode())
                    await self.writer.drain()
        except asyncio.CancelledError:
            pass
        finally:
            if self.writer:
                self.writer.close()

    async def run(self) -> None:
        """
        Подключается к серверу и запускает асинхронные задачи на прием и отправку сообщений.
        :return: None
        """
        if not await self.connect():
            return
        tasks = [
            asyncio.create_task(self.receive_messages()),
            asyncio.create_task(self.send_messages()),
        ]
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        logger.info("Shut down")


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
