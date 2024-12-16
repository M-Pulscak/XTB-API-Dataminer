import json
import socket
import logging
import time
import ssl
from threading import Thread

WRAPPER_NAME = 'Python'
WRAPPER_VERSION = '3.0'

"""**************   Zde zadej své přihlašovací údaje:   ****************"""
userId = 12345678                      # Číslo účtu
password = "Tvoje_Heslo"             # Heslo
appName = 'PuMi Trader'              # Název této aplikace

"""****************   Nastavení XTB API serveru:   *******************"""
XAPI_URL = 'xapi.xtb.com'          # URL Serveru
XAPI_PORT = 5124                    # DEMO: RR port:5124 Stream:5125 REAL: RR port:5112 Stream:5113
XAPI_STREAM_PORT = 5125      # Streaming Port
CONN_TRIES = 3                       # Maximum pokusů o připojení
API_TIMEOUT = 0.1                   # API inter-command timeout (sec)

"""*****************     Nastavení Loggeru:     ***********************"""
logger = logging.getLogger("jsonSocket")
FORMAT = '[%(asctime)s][%(funcName)s:%(lineno)d] %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)  # Level: DEBUG INFO WARNING ERROR CRITICAL
"""*************************************************************"""


class TransactionSide:
    BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP = range(6)


class TransactionType:
    ORDER_OPEN, ORDER_CLOSE, ORDER_MODIFY, ORDER_DELETE = range(4)


"""***************************************************************
     V    V    V    V    V              JSON  Socket                V    V    V    V    V    V
****************************************************************"""


class JsonSocket:
    def __init__(self, address, port, encrypt=False):
        self._ssl = encrypt
        self.socket = self._create_socket(address) if encrypt else socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn = self.socket
        self._timeout = None
        self._address = address
        self._port = port
        self._decoder = json.JSONDecoder()
        self._buffered_data = ''

    def _create_socket(self, address):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        context = ssl.create_default_context()
        return context.wrap_socket(sock, server_hostname=address)

    def connect(self):
        for attempt in range(CONN_TRIES):
            try:
                self.socket.connect((self._address, self._port))
                logger.info("Socket connected")
                return True
            except socket.error as msg:
                logger.error(f"Connection attempt {attempt + 1} failed: {msg}")
                time.sleep(0.25)
        return False

    def _send_obj(self, obj):
        msg = json.dumps(obj)
        self._send_message(msg)

    def _send_message(self, msg):
        if not self.socket:
            raise RuntimeError("Socket connection broken")
        encoded_msg = msg.encode('utf-8')
        sent = 0
        while sent < len(encoded_msg):
            sent += self.conn.send(encoded_msg[sent:])
            logger.info(f'Sent: {msg}')
            time.sleep(API_TIMEOUT)

    def _read_data(self, buffer_size=4096):
        while True:
            char = self.conn.recv(buffer_size).decode()
            self._buffered_data += char
            try:
                resp, size = self._decoder.raw_decode(self._buffered_data)
                self._buffered_data = self._buffered_data[size:].strip()
                logger.info(f'Received: {resp}')
                return resp
            except ValueError:
                continue

    def close(self):
        logger.debug("Closing socket")
        self.socket.close()
        if self.socket is not self.conn:
            self.conn.close()

    def set_timeout(self, timeout):
        self._timeout = timeout
        self.socket.settimeout(timeout)


"""***************************************************************
     V    V    V    V             API  Request-Response  Klient               V    V    V    V
****************************************************************"""


class APIClient(JsonSocket):
    def __init__(self, address=XAPI_URL, port=XAPI_PORT, encrypt=True):
        super().__init__(address, port, encrypt)
        if not self.connect():
            raise Exception(f"Cannot connect to {address}:{port} after {CONN_TRIES} retries")

    def execute(self, command):
        self._send_obj(command)
        return self._read_data()

    def command_execute(self, command_name, arguments=None):
        return self.execute(base_command(command_name, arguments))

    def disconnect(self):
        self.close()


"""***************************************************************
    V    V    V    V    V                API  Stream Klient              V    V    V    V    V
****************************************************************"""


class APIStreamClient(JsonSocket):
    def __init__(self, address=XAPI_URL, port=XAPI_STREAM_PORT, encrypt=True, ssid=None,
                 handlers=None):
        super().__init__(address, port, encrypt)
        self._ssid = ssid
        self._handlers = handlers if handlers else {}
        self._running = self.connect()
        self._thread = Thread(target=self._stream_listener)
        self._thread.start()

    def execute(self, command):
        self._send_obj(command)

    def subscribe(self, command, params):
        self.execute(dict(command=command, **params))

    def unsubscribe(self, command, params):
        self.execute(dict(command=command, **params))

    def _stream_listener(self):
        while self._running:
            msg = self._read_data()
            handler = self._handlers.get(msg.get("command"))
            if handler:
                handler(msg)
            logger.info(f"Stream received: {msg}")

    def disconnect(self):
        self._running = False
        self._thread.join()
        self.close()


"""************************************************************"""


def proc_tick_example(msg): print("TICK:", msg)
def proc_trade_example(msg): print("TRADE:", msg)
def proc_balance_example(msg): print("BALANCE:", msg)
def proc_trade_status_example(msg): print("TRADE STATUS:", msg)
def proc_profit_example(msg): print("PROFIT:", msg)
def proc_news_example(msg): print("NEWS:", msg)


def base_command(command_name, arguments=None):
    return dict(command=command_name, arguments=arguments or {})


def login_command(user_id, pas, app):
    return base_command('login', dict(userId=user_id, password=pas, appName=app))


"""***************************************************************
    V    V    V    V    V                Main Program              V    V    V    V    V
****************************************************************"""


def main(user, pas, app):
    client = APIClient()
    login_response = client.execute(login_command(user_id=user, pas=pas, app=app))
    logger.info(str(login_response))

    if not login_response.get('status'):
        print(f'Login failed. Error code: {login_response.get("errorCode")}')
        return

    ssid = login_response.get('streamSessionId')

    handlers = {
        "tickPrices": proc_tick_example,
        "trade": proc_trade_example,
        "balance": proc_balance_example,
        "tradeStatus": proc_trade_status_example,
        "profit": proc_profit_example,
        "news": proc_news_example,
    }

    stream = APIStreamClient(ssid=ssid, handlers=handlers)

    stream.subscribe('getTrades', {'streamSessionId': ssid})
    stream.subscribe('getTickPrices', {'symbol': 'EURUSD', 'streamSessionId': ssid})

    time.sleep(5)

    stream.disconnect()
    client.disconnect()


if __name__ == "__main__":
    main(userId, password, appName)
