from telethon.sync import TelegramClient
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
from telethon.errors.rpcerrorlist import FloodWaitError
from telethon.tl.custom import message
from telethon.tl import types
from datetime import datetime, timedelta
import argparse, asyncio, os, logging, dotenv, json, zoneinfo, textwrap


# ----------------------------------------------------------------------------------------------------------------------

def args_parse(args_line: list[str] = None) -> argparse.Namespace:
    """
    Парсер аргументов командной строки

    Args:
        args_line: список аргументов формата ['-X', '...']
    """
    parser = argparse.ArgumentParser(description='Скрипт для выгрузки переписок с контактами с аккаунта Telegram',
                                     add_help=False)

    parser.add_argument('-h',
                        action='help', default=argparse.SUPPRESS,
                        help='Показать help сообщение и выйти')
    parser.add_argument('-q',
                        action='store_true', dest='QUIET',
                        help='Скрыть логи, оставить только вывод')
    parser.add_argument('-j',
                        action='store_true', dest='JSON',
                        help='Вывести результат в json формате')
    parser.add_argument('-f',
                        type=str, dest='FILE_NAME',
                        help='Записывать результат работы скрипта в указанный файл, а не в консоль')
    parser.add_argument('-s',
                        type=str, default='TG_Session.session', dest='SESSION_FILE',
                        help='Путь до файла Telegram сессии (default=TG_Session.session)')
    parser.add_argument('-t',
                        type=int, default=30, dest='TIMEOUT',
                        help='Таймаут подключения в секундах (default=30)')
    parser.add_argument('-l',
                        type=int, default=10, dest='LIMIT',
                        help='Количество последних сообщений контакта для выгрузки (default=10)')
    parser.add_argument('-tz',
                        type=str, dest='TIMEZONE',
                        help='Часовой пояс, влияет на временные метки у выгруженных сообщений (default=Время системы)')
    parser.add_argument('-fl',
                        type=int, default=1048576, dest='FILE_LIMIT',
                        help='Максимальный размер файлов в байтах, которые скрипт будет выгружать (default=1048576)')
    parser.add_argument('-d',
                        type=str, dest='DOWNLOADS', nargs='?', const='', default=None,
                        help='Скачивать медиа объекты из переписок. По умолчанию создаётся папка downloads '
                             'в месте расположения скрипта. Можно также указать свой путь, он не будет создан')

    parser.add_argument('CONTACT_IDENTIFIER',
                        type=str,
                        help='ID/username/name нужного контакта')

    return parser.parse_args(args_line)


def setup_logger(in_file: bool = True, is_quiet: bool = False) -> logging.Logger:
    """
    Создание логгера

    Args:
        in_file: записывать логи в файл (=true) или выводить в консоль (=false)
        is_quiet: подавить вывод (=true) или нет (=false)
    """
    some_logger = logging.getLogger(__name__)
    some_logger.setLevel(logging.INFO)
    if in_file:
        info_handler = logging.FileHandler('log.txt', mode='a', encoding='utf-8')
    else:
        info_handler = logging.StreamHandler()
    info_handler.setLevel(logging.INFO)
    info_formatter = logging.Formatter('[%(asctime)s] - %(levelname)s - %(funcName)s - %(message)s')
    info_handler.setFormatter(info_formatter)
    some_logger.addHandler(info_handler)
    if is_quiet:
        logging.disable(logging.CRITICAL)

    return some_logger


async def connect_to_tg(tg_client: TelegramClient, connection_timeout: int) -> None:
    """
    Подключение к серверам Telegram с использованием объекта типа TelegramClient из библиотеки telethon

    Args:
        tg_client: экзепляр объекта TelegramClient
        connection_timeout: время таймаута при подключении к серверам Telegram
    """
    try:
        await asyncio.wait_for(tg_client.start(), timeout=connection_timeout)
    except asyncio.TimeoutError:
        logger.error(f'Таймаут при соединении с сервером (>{connection_timeout} секунд)')
        exit(-1)
    except asyncio.IncompleteReadError:
        logger.error(f'Файл сессии не подходит для установления соединения')
        exit(-1)
    except FloodWaitError:
        logger.error('Ошибка, Telegram блокирует подключение из-за прошлых неуспешных попыток, нужно подождать 1 час\n')
        exit(-1)
    logger.info('Успешная авторизация')


def change_timezone(timezone: str = None) -> timedelta:
    """
    Получение временного смещения относительно UTC для предоставленного часового пояса

    Args:
        timezone: название часового пояса в формате Europe/Moscow
    """
    # Если часовой пояс не указан, то используется системное время
    if not timezone:
        current_time = datetime.now().astimezone()
        time_offset = current_time.utcoffset()
    else:
        tz = zoneinfo.ZoneInfo(timezone)
        current_time = datetime.now(tz)
        time_offset = current_time.utcoffset()

    return time_offset


def get_contact_info(contact: types.User | types.Chat | types.Channel) -> dict:
    """
    Получить информацию о типе, ID и именах предоставленного объекта класса User, Chat или Channel в
    формате словаря с полями 'ID', 'Type', 'Username' и 'Title'/'Name'

    Args:
        contact: объект контакта
    """
    # Тип объекта
    contact_type = type(contact).__name__
    # Проверка наличия имени формата @username
    contact_username = None
    if hasattr(contact, 'username'):
        if contact.username:
            contact_username = f'@{contact.username}'

    # Формирование словаря
    info = None
    match contact_type:
        case 'User':
            name = f'{contact.first_name if contact.first_name else ""} ' \
                   f'{contact.last_name if contact.last_name else ""}'.strip()
            if not name:
                name = None

            info = {'ID': contact.id,
                    'Type': contact_type,
                    'Username': contact_username,
                    'Name': name}
        case 'Chat':
            info = {'ID': contact.id,
                    'Type': contact_type,
                    'Username': contact_username,
                    'Title': contact.title}
        case 'Channel':
            info = {'ID': contact.id,
                    'Type': contact_type,
                    'Username': contact_username,
                    'Title': contact.title}
        case _:
            logger.error(f'Неизвестный формат контакта: {contact_type}')
            exit(-1)

    return info


async def download_media(tg_client: TelegramClient,
                         dialog_message: message,
                         download_path: str,
                         file_limit: int) -> str:
    """
    Скачивание файловых вложений из предоставленного объекта сообщения

    Args:
        tg_client: экзепляр объекта TelegramClient
        dialog_message: экзепляр объекта сообщения
        download_path: путь, куда будут сохраняться вложения
        file_limit: предел размера скачиваемых файлов
    """
    if download_path == '':
        download_path = 'downloads'
        os.makedirs(download_path, exist_ok=True)

    if not os.path.exists(download_path):
        logger.error(f'Указанный путь {download_path} не существует')
        exit(-1)

    filename = f'{dialog_message.date.strftime("%Y%m%d_%H%M%S")}_{dialog_message.id}'
    try:
        filesize = dialog_message.media.document.size
    except AttributeError:
        filesize = 0

    if filesize > file_limit:
        return f'file too large {filesize}'

    file_already_exists = None
    for item in os.listdir(download_path):
        if filename == os.path.splitext(item)[0]:
            file_already_exists = os.path.join(download_path, item)
            break

    if not file_already_exists:
        file_already_exists = await tg_client.download_media(dialog_message, file=os.path.join(download_path, filename))

    return file_already_exists


async def get_dialog(tg_client: TelegramClient,
                     contact_identifier: str,
                     messages_limit: int,
                     is_json: bool,
                     file_limit: int,
                     download_path: None | str,
                     timezone: str = None) -> str:
    """
    Получение всех сообщений между переданным в функцию объектом TelegramClient и контактом, указываемым с помощью
    contact_identifier, полученные данные форматируются либо в человекочитаемую таблицу, либо в json словарь. При
    наличии соответствующих флагов, скачивает вложения из обработанных сообщений и форматирует время под нужный
    часовой пояс

    Args:
        tg_client: экзепляр объекта TelegramClient
        contact_identifier: идентификатор контакта (ID, Username или имя)
        messages_limit: количество последних сообщений из переписки, которые нужно обработать
        is_json: флаг включения json формата (=true), иначе формируется таблица (=false)
        file_limit: предел размера скачиваемых файлов
        download_path: путь, куда будут сохраняться вложения
        timezone: название часового пояса в формате Europe/Moscow
    """
    dialog = {}
    # Дефолтный формат словаря dialog после завершения работы функции:
    # {
    #   'contact_info':
    #                   {
    #                     'ID контакта' (int): _
    #                     'Тип контакта' (str): _
    #                     '@ссылка контакта' (str): _
    #                     'Имя контакта' (str): _
    #                   }
    #   'messages':
    #               [
    #                 {
    #                   'Дата и время отправки' (str): _
    #                   'Отправитель':
    #                                  {
    #                                    'ID контакта' (int): _
    #                                    'Тип контакта' (str): _
    #                                    '@ссылка контакта' (str): _
    #                                    'Имя контакта' (str): _
    #                                  }
    #                   'Текст сообщения' (str): _
    #                   'Наличие вложений' (str/bool): _
    #                   'Переслано ли сообщение' (bool): _
    #                 },
    #                 {
    #                   ...
    #                 },
    #                 ...
    #               ]
    # }
    try:
        contact = await tg_client.get_entity(contact_identifier)
    except ValueError:
        logger.error(f'Не найдена сущность {contact_identifier}')
        exit(-1)
    dialog['contact_info'] = get_contact_info(contact)
    dialog['messages'] = []

    async for dialog_message in tg_client.iter_messages(contact, limit=messages_limit):
        # Обработка возможных вложений в сообщении
        if dialog_message.media and download_path is not None:  # Есть вложение, и указан флаг -d
            filename = await download_media(tg_client, dialog_message, download_path, file_limit)
        elif dialog_message.media and download_path is None:  # Есть вложение, но не указан флаг -d
            filename = True
        elif not dialog_message.media and download_path is not None:  # Нет вложения, и указан флаг -d
            filename = None
        elif not dialog_message.media and download_path is None:  # Нет вложения, но не указан флаг -d
            filename = False

        message_date = (dialog_message.date + change_timezone(timezone)).strftime("%Y-%m-%d %H:%M:%S")
        # Если нужно изменить состав полей, то достаточно изменить строку ниже, остальные структуры функции адаптируются
        # Можно добавлять или убирать любые поля, КРОМЕ 'sender' и 'text', они прописаны в форматировании таблицы
        entry = {'date': message_date,
                 # Telethon выгружает сообщения в ублюдском формате и зачем-то парсит отправителя в разные поля
                 # в зависимости от того, входящее сообщение или исходящее. Чтобы не плясать лишний раз с бубном
                 # используется прямое обращение в скрытому полю _sender
                 'sender': get_contact_info(dialog_message._sender),
                 'text': dialog_message.text,
                 'media': filename,
                 'is_forwarded': bool(dialog_message.fwd_from)}

        dialog['messages'].append({dialog_message.id: entry})
        # Путь до описания класса message, экзепляры которого итерируются в tg_client.iter_messages():
        # ./venv/Lib/site-packeges/telethon/tl/custom/message.py

    # Изменение порядка сообщений, в выгрузке сообщения идут так: последнее, предпоследнее и т.д.
    # Читать сообщения в таком порядке придётся снизу вверх, чтобы соблюдать хронологию. Это неудобно
    reversed_messages = dialog['messages'][::-1]
    dialog['messages'] = reversed_messages

    # Формирование вывода
    data: str = ''
    if is_json:
        data = json.dumps(obj=dialog, indent=4, ensure_ascii=False)
    else:
        # Вычисление выравнивания для столбцов на основе значений из dialog['contact_info']
        sizes = [0 for _ in range(4)]
        dialog_dict_path = dialog['contact_info']
        for contact_field in dialog_dict_path:
            # Получаем позицию поля в словаре
            position = list(dialog_dict_path.keys()).index(contact_field)
            # Получаем длину значения поля с учётом ключа этого поля
            field_value_len = len(str(dialog_dict_path[contact_field]) + contact_field + ': ')
            # Ширина столбца с обрабатываемым полем
            if field_value_len > sizes[position]:
                sizes[position] = field_value_len

        # Вычисление выравнивания для столбцов на основе значений из dialog['messages']['sender']
        dialog_dict_path = dialog['messages']
        for dialog_message in dialog_dict_path:
            # Получаем словарь с данными отправителя сообщения
            sender_info = dialog_message[list(dialog_message.keys())[0]]['sender']
            for contact_field in sender_info:
                # Получаем позицию поля в словаре
                position = list(sender_info.keys()).index(contact_field)
                # Получаем длину значения поля с учётом ключа этого поля
                field_value_len = len(str(sender_info[contact_field]) + contact_field + ': ')
                # Ширина столбца с обрабатываемым полем
                if field_value_len > sizes[position]:
                    sizes[position] = field_value_len

        # Функция для форматирования заголовка, содержащего данные контакта или отправителя сообщения
        def title_formating(some_dict: dict):
            title = ' '
            for number, field in enumerate(list(some_dict.keys())):
                segment = f'{field}: {some_dict[field]}'
                title += f'{segment:<{sizes[number]}} '
                if number < len(sizes) - 1:
                    title += '| '
            return title

        # Заголовок
        data += 'ВЫГРУЗКА КОНТАКТА:' + '\n' * 2
        title_string = title_formating(dialog['contact_info'])
        message_size = len(title_string)
        delimiter = '-' * message_size
        data += title_string + '\n'

        # Строки
        data += '\n' * 2 + 'СООБЩЕНИЯ:' + '\n' * 2
        dialog_dict_path = dialog['messages']
        for dialog_message in dialog_dict_path:
            key_value = dialog_message[list(dialog_message.keys())[0]]
            data += '\n' + title_formating(key_value['sender']) + '\n'
            data += delimiter + '\n'
            data += f'Date: {key_value["date"]}' + '\n'
            data += f'Have media: {key_value["media"]}' + '\n'
            data += f'Is forwarded: {key_value["is_forwarded"]}' + '\n'
            data += 'Text:'
            if key_value["text"]:
                offset = 5
                filled = textwrap.fill(key_value["text"], width=message_size - offset)
                result = textwrap.indent(filled, offset * " ")
                data += '\n' + result
            else:
                data += ' None'
            data += '\n'

    return data


async def main(some_arguments: argparse.Namespace,
               some_api_id: int | str,
               some_api_hash: str,
               some_proxy: tuple) -> None:
    logger.info('Скрипт запущен')

    # При отсутствии файла Telegram сессии скрипт прерывается
    if os.path.exists(some_arguments.SESSION_FILE):
        logger.info(f'Используется сессия {some_arguments.SESSION_FILE}')
    else:
        logger.error(f'Не найден файл сессии {some_arguments.SESSION_FILE}, используйте скрипт create_session.py')
        exit(-1)

    # Создание экзепляра объекта TelegramClient с использованием TG API и прокси
    # (при написании использовался TG WS Proxy, с ним всё работает, остальное не факт)
    client = TelegramClient(some_arguments.SESSION_FILE, int(some_api_id), some_api_hash,
                            connection=ConnectionTcpMTProxyRandomizedIntermediate,
                            proxy=some_proxy)

    await connect_to_tg(tg_client=client, connection_timeout=some_arguments.TIMEOUT)

    result = await get_dialog(tg_client=client,
                              contact_identifier=some_arguments.CONTACT_IDENTIFIER,
                              messages_limit=some_arguments.LIMIT,
                              is_json=some_arguments.JSON,
                              file_limit=some_arguments.FILE_LIMIT,
                              download_path=some_arguments.DOWNLOADS,
                              timezone=some_arguments.TIMEZONE)

    # Вывод result в консоль или в файл
    if some_arguments.FILE_NAME:
        file_name = some_arguments.FILE_NAME
        with open(file=file_name, mode='w', encoding='utf-8') as some_file:
            some_file.write(result)
    else:
        print(result)

    # Завершение соединения
    await client.disconnect()
    logger.info('Скрипт успешно завершён\n')


# ----------------------------------------------------------------------------------------------------------------------

# Смена директории исполнения скрипта
os.chdir(path=os.path.dirname(__file__))

# Подгрузка секретов из файла .env, создание экзепляра прокси и парсинг аргументов
dotenv.load_dotenv('.env')
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
proxy = (os.getenv('PROXY_IP'), int(os.getenv('PROXY_PORT')), os.getenv('PROXY_SECRET'))
arguments = args_parse()

# Создание логгера
logger = setup_logger(in_file=False, is_quiet=arguments.QUIET)

# Запуска основной функции
asyncio.run(
    main(some_arguments=arguments, some_api_id=api_id, some_api_hash=api_hash, some_proxy=proxy)
)
