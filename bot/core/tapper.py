import asyncio
import random
import time
from urllib.parse import unquote

import aiohttp
import json
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw import types
from .agents import generate_random_user_agent
from bot.config import settings
from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers


class Tapper:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.user_id = 0
        self.username = None
        self.first_name = None
        self.last_name = None
        self.fullname = None
        self.time_end = 0

        self.session_ug_dict = self.load_user_agents() or []

        headers['User-Agent'] = self.check_user_agent()

    async def generate_random_user_agent(self):
        return generate_random_user_agent(device_type='android', browser_type='chrome')

    def save_user_agent(self):
        user_agents_file_name = "user_agents.json"

        if not any(session['session_name'] == self.session_name for session in self.session_ug_dict):
            user_agent_str = generate_random_user_agent()

            self.session_ug_dict.append({
                'session_name': self.session_name,
                'user_agent': user_agent_str})

            with open(user_agents_file_name, 'w') as user_agents:
                json.dump(self.session_ug_dict, user_agents, indent=4)

            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | User agent saved successfully")

            return user_agent_str

    def load_user_agents(self):
        user_agents_file_name = "user_agents.json"

        try:
            with open(user_agents_file_name, 'r') as user_agents:
                session_data = json.load(user_agents)
                if isinstance(session_data, list):
                    return session_data

        except FileNotFoundError:
            logger.warning("User agents file not found, creating...")

        except json.JSONDecodeError:
            logger.warning("User agents file is empty or corrupted.")

        return []

    def check_user_agent(self):
        load = next(
            (session['user_agent'] for session in self.session_ug_dict if session['session_name'] == self.session_name),
            None)

        if load is None:
            return self.save_user_agent()

        return load

    async def get_tg_web_data(self, proxy: str | None) -> str:
        if proxy:
            proxy = Proxy.from_str(proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            with_tg = True

            if not self.tg_client.is_connected:
                with_tg = False
                try:
                    await self.tg_client.connect()
                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

            while True:
                try:
                    peer = await self.tg_client.resolve_peer('HexacoinBot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"<light-yellow>{self.session_name}</light-yellow> | FloodWait {fl}")
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Sleep {fls}s")

                    await asyncio.sleep(fls + 3)

            InputBotApp = types.InputBotAppShortName(bot_id=peer, short_name="wallet")

            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotApp,
                platform='android',
                write_allowed=True,
            ))

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(
                    string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0]))

            try:
                information = await self.tg_client.get_me()
                self.user_id = information.id
                self.first_name = information.first_name or ''
                self.last_name = information.last_name or ''
                self.username = information.username or ''
            except Exception as e:
                print(e)

            self.fullname = f'{self.first_name} {self.last_name}'.strip()

            if with_tg is False:
                await self.tg_client.disconnect()

            return tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)

    async def auth(self, http_client: aiohttp.ClientSession, init_data):
        try:
            json = {"data": init_data}
            response = await http_client.post(url='https://ago-api.hexacore.io/api/app-auth', json=json,
                                              ssl=False)
            response.raise_for_status()
            response_json = await response.json()
            return response_json.get('token')
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while auth {error}")

    async def register(self, http_client: aiohttp.ClientSession, init_data):
        try:
            json = {}

            if http_client.headers['Authorization'] is None or http_client.headers['Authorization'] == '':
                http_client.headers['Authorization'] = await self.auth(http_client=http_client, init_data=init_data)

            if settings.REF_ID == '':
                referer_id = "737844465"
            else:
                referer_id = str(settings.REF_ID)  # Ensure referer_id is a string

            if self.username != '':
                json = {
                    "user_id": int(self.user_id),  # Ensure user_id is a string
                    "fullname": f"{str(self.fullname)}",
                    "username": f"{str(self.username)}",
                    "referer_id": f"{str(referer_id)}"
                }

            if self.username != '':
                json = {
                    "user_id": int(self.user_id),  # Ensure user_id is a string
                    "fullname": f"{str(self.fullname)}",
                    "username": f"{str(self.username)}",
                    "referer_id": f"{str(referer_id)}"
                }
                response = await http_client.post(url='https://ago-api.hexacore.io/api/create-user', json=json,
                                                  ssl=False)
                #print(await response.text())
                #print(await response.json())
                if response.status == 409:
                    return 'registered'
                if response.status in (200, 201):
                    return True
                if response.status not in (200, 201, 409):
                    logger.critical(f"<light-yellow>{self.session_name}</light-yellow> | Something wrong with "
                                    f"register! {response.status}")
                    return False
            else:
                logger.critical(f"<light-yellow>{self.session_name}</light-yellow> | Error while register, "
                                f"please add username to telegram account, bot will not work!!!")
                return False
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while register {error}")

    async def get_taps(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url='https://ago-api.hexacore.io/api/available-taps', ssl=False)
            response_json = await response.json()
            taps = response_json.get('available_taps')
            boosters = response_json.get('available_boosters')
            return taps, boosters
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while get taps {error}")

    async def get_balance(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/balance/{self.user_id}', ssl=False)
            response_json = await response.json()
            return response_json
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while get balance {error}")

    async def do_taps(self, http_client: aiohttp.ClientSession, taps):
        try:
            json = {"taps": taps}
            response = await http_client.post(url=f'https://ago-api.hexacore.io/api/mining-complete', json=json,
                                              ssl=False)
            response_json = await response.json()

            if not response_json.get('success'):
                return False

            return True

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while do taps {error}")

    async def use_booster(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.post("https://ago-api.hexacore.io/api/activate-boosters", ssl=False)
            resp_json = await response.json()
            success = resp_json.get('success')
            return success
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | use booster error - {error}")

    async def get_missions(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/missions', ssl=False)
            response_json = await response.json()
            incomplete_mission_ids = [mission['id'] for mission in response_json if (not mission['isCompleted']
                                                                                     and mission['autocomplete'])]

            return incomplete_mission_ids
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while get missions {error}")

    async def do_mission(self, http_client: aiohttp.ClientSession, id):
        try:
            json = {'missionId': id}
            response = await http_client.post(url=f'https://ago-api.hexacore.io/api/mission-complete', json=json,
                                              ssl=False)
            response_json = await response.json()
            if not response_json.get('success'):
                return False
            return True
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while doing missions {error}")

    async def get_level_info(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/level', ssl=False)
            response_json = await response.json()
            lvl = response_json.get('lvl')
            upgrade_available = response_json.get('upgrade_available', None)
            upgrade_price = response_json.get('upgrade_price', None)
            new_lvl = response_json.get('next_lvl', None)
            return (lvl,
                    upgrade_available,
                    upgrade_price, new_lvl)
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while get level {error}")

    async def level_up(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.post(url=f'https://ago-api.hexacore.io/api/upgrade-level', ssl=False)
            response_json = await response.json()
            if not response_json.get('success'):
                return False
            return True
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while up lvl {error}")

    async def play_game_1(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/in-game-reward-available/1/'
                                                 f'{self.user_id}', ssl=False)
            response_json = await response.json()
            if response_json.get('available'):
                json = {"game_id": 1, "user_id": self.user_id}
                response1 = await http_client.post(url=f'https://ago-api.hexacore.io/api/in-game-reward', json=json,
                                                   ssl=False)
                if response1.status in (200, 201):
                    return True
            else:
                return False

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 1 {error}")

    async def play_game_2(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/in-game-reward-available/2/'
                                                 f'{self.user_id}', ssl=False)
            response_json = await response.json()
            if response_json.get('available'):
                json = {"game_id": 2, "user_id": self.user_id}
                response1 = await http_client.post(url=f'https://ago-api.hexacore.io/api/in-game-reward', json=json,
                                                   ssl=False)
                if response1.status in (200, 201):
                    return True
            else:
                return False

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 2 {error}")

    async def play_game_3(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.post(url=f'https://ago-api.hexacore.io/api/games/3/sessions/start', ssl=False)
            #print(await response.text())
            response = await http_client.get(url=f'https://dirty-job-server.hexacore.io/game/start?'
                                                 f'playerId={self.user_id}', ssl=False)
            text = await response.text()
            #print(response.status, text[:64])
            response.raise_for_status()
            response_json = await response.json()

            level = response_json.get('playerState').get('currentGameLevel')

            games_count = len(response_json.get('gameConfig').get('gameLevels', {}))

            for i in range(level + 1, games_count):
                json = {"type": "EndGameLevelEvent", "playerId": str(self.user_id), "level": int(i), "boosted": False,
                        "transactionId": None}
                response1 = await http_client.post(url=f'https://dirty-job-server.hexacore.io/game/end-game-level',
                                                   json=json, ssl=False)

                if response1.status in (200, 201):
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Done {i} lvl in dirty job")

                elif response1.status == 400:
                    logger.warning(f"<light-yellow>{self.session_name}</light-yellow> | Reached max games for today in "
                                   f"dirty job")
                    break

                await asyncio.sleep(1)

            balance = response_json.get('playerState').get('inGameCurrencyCount')
            owned_items = response_json.get('playerState').get('hubItems')
            available_items = response_json.get('gameConfig').get('hubItems')

            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Trying to upgrade items in dirty job, "
                        f"wait a bit")

            old_auth = http_client.headers['Authorization']

            if http_client.headers['Authorization']:
                del http_client.headers['Authorization']

            for item_name, item_info in available_items.items():
                if item_name not in owned_items:
                    upgrade_level_info = list(map(int, item_info['levels'].keys()))
                    level_str = str(upgrade_level_info[0])
                    price = item_info['levels'][level_str]['inGameCurrencyPrice']
                    ago = item_info['levels'][level_str]['agoReward']

                    if balance >= price:
                        purchase_data = {
                            "type": "UpgradeHubItemEvent",
                            "playerId": str(self.user_id),
                            "itemId": str(item_name),
                            "level": int(upgrade_level_info[0])
                        }
                        purchase_response = await http_client.post(
                            url='https://dirty-job-server.hexacore.io/game/upgrade-hub-item',
                            json=purchase_data, ssl=False)

                        if purchase_response.status in (200, 201):
                            logger.success(f"<light-yellow>{self.session_name}</light-yellow> | "
                                           f"Purchased new item {item_name} for {price} currency in dirty job game, "
                                           f"got {ago} AGO")
                            balance -= price
                            owned_items[item_name] = {'level': upgrade_level_info[0]}
                        else:
                            logger.warning(
                                f"Failed to purchase new item {item_name}. Status code: {purchase_response.status}, text:"
                                f" {await purchase_response.text()}, headers - \n{http_client.headers}")

                elif item_name in owned_items:
                    current_level = int(owned_items[item_name]['level'])
                    upgrade_level_info = list(map(int, item_info['levels'].keys()))

                    next_levels_to_upgrade = [level for level in upgrade_level_info if level > current_level]

                    if not next_levels_to_upgrade:
                        continue

                    for level in next_levels_to_upgrade:
                        level_str = str(level)
                        price = item_info['levels'][level_str]['inGameCurrencyPrice']
                        ago = item_info['levels'][level_str]['agoReward']

                        if balance >= price:
                            purchase_data = {
                                "type": "UpgradeHubItemEvent",
                                "playerId": str({self.user_id}),
                                "itemId": str({item_name}),
                                "level": int(level)
                            }
                            purchase_response = await http_client.post(
                                url='https://dirty-job-server.hexacore.io/game/upgrade-hub-item',
                                json=purchase_data, ssl=False)

                            if purchase_response.status in (200, 201):
                                logger.success(f"<light-yellow>{self.session_name}</light-yellow> | "
                                               f"Purchased upgrade for {item_name} for {price} currency in dirty job "
                                               f"game, got {ago} AGO")
                                balance -= price
                                owned_items[item_name]['level'] = level
                            else:
                                logger.warning(
                                    f"Failed to purchase upgrade for {item_name}. Status code: "
                                    f"{purchase_response.status}")

                await asyncio.sleep(0.5)

            http_client.headers['Authorization'] = old_auth
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 3 {error}")

    async def play_game_5(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.post("https://ago-api.hexacore.io/api/games/5/sessions/start", ssl=False)
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/in-game-reward-available/5/'
                                                 f'{self.user_id}', ssl=False)
            response_json = await response.json()
            if response_json.get('available'):
                json = {"game_id": 5, "user_id": self.user_id}
                response1 = await http_client.post(url=f'https://ago-api.hexacore.io/api/in-game-reward', json=json,
                                                   ssl=False)
                if response1.status in (200, 201):
                    return True
            else:
                return False

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while play game 5 {error}")

    async def play_game_6(self, http_client: aiohttp.ClientSession):
        try:
            old_auth = http_client.headers['Authorization']

            response = await http_client.post("https://ago-api.hexacore.io/api/games/6/sessions/start", ssl=False)

            http_client.headers['Authorization'] = str(self.user_id)

            response = await http_client.get(url=f'https://hurt-me-please-server.hexacore.io/game/start', ssl=False)
            response.raise_for_status()
            response_json = await response.json()

            current_level = response_json.get('playerState').get('currentGameLevel')
            if current_level == 0:
                current_level = 1
            else:
                current_level += 1

            limit = response_json.get('gameConfig').get('freeSessionGameLevelsMaxCount')
            if limit == 0:
                logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Hurt me game cooldown")

            while limit != 0:
                json = {"type": "EndGameLevelEvent",
                        "level": int(current_level),
                        "agoClaimed": float(99.75+random.randint(1, 5)),
                        "boosted": False,
                        "transactionId": None}

                response1 = await http_client.post(url=f'https://hurt-me-please-server.hexacore.io/game/event',
                                                   json=json, ssl=False)

                if response1.status in (200, 201):
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Done {current_level} lvl in "
                                f"Hurt me please")
                else:
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Hurt me game cooldown")
                    break
                current_level += 1
                limit -= 1

                await asyncio.sleep(0.5)

            http_client.headers['Authorization'] = old_auth

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while play game Hurt me please"
                         f" {error}")

    async def daily_checkin(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/daily-checkin', ssl=False)
            response_json = await response.json()

            status = response_json.get('is_available')
            next_day = response_json.get('next')

            if status is True:
                json_payload = {"day": next_day}
                response_daily = await http_client.post(url=f'https://ago-api.hexacore.io/api/daily-checkin',
                                                        json=json_payload, ssl=False)
                response_json_daily = await response_daily.json()
                if response_json_daily.get('success') is True:
                    return True, next_day
                else:
                    return False, None
            else:
                return False, None
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while daily reward {error}")

    async def get_tap_passes(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(url=f'https://ago-api.hexacore.io/api/get-tap-passes', ssl=False)
            response_json = await response.json()
            return response_json
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while getting tap passes {error}")

    async def buy_tap_pass(self, http_client: aiohttp.ClientSession):
        try:
            json = {"name": "7_days"}
            response = await http_client.post(url=f'https://ago-api.hexacore.io/api/buy-tap-passes', json=json,
                                              ssl=False)
            response_json = await response.json()
            if response_json.get('status') is False:
                return False
            return True
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Error while getting tap passes {error}")

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(45), ssl=False)
            ip = (await response.json()).get('origin')
            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Proxy: {proxy} | Error: {error}")

    async def run(self, proxy: str | None) -> None:
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        http_client = aiohttp.ClientSession(headers=headers,
                                            connector=proxy_conn)

        if proxy:
            await self.check_proxy(http_client=http_client, proxy=proxy)

        init_data = await self.get_tg_web_data(proxy=proxy)

        while True:
            try:
                http_client.headers['Authorization'] = await self.auth(http_client=http_client, init_data=init_data)
                status = await self.register(http_client=http_client, init_data=init_data)
                if status is True:
                    logger.success(f"<light-yellow>{self.session_name}</light-yellow> | Successfully account register")
                elif status == 'registered':
                    pass

                info = await self.get_balance(http_client=http_client)
                balance = info.get("balance") or 0
                logger.info(f'<light-yellow>{self.session_name}</light-yellow> | Balance: {balance}')

                status, next_day = await self.daily_checkin(http_client=http_client)
                if status is True and next_day is not None:
                    logger.success(f'<light-yellow>{self.session_name}</light-yellow> | Daily checkin claimed, '
                                   f'streak - {next_day}')

                if settings.AUTO_BUY_PASS:
                    logger.critical(f"<light-yellow>{self.session_name}</light-yellow> | Passes wont work, tg bot issue, not buying")
                    #data = await self.get_tap_passes(http_client=http_client)
                    #if data.get('active_tap_pass') is None and balance >= 1000:
                    #    status = await self.buy_tap_pass(http_client=http_client)
                    #    if status:
                    #        logger.success(
                    #            f'<light-yellow>{self.session_name}</light-yellow> | Bought taps pass for 7 days')

                if settings.AUTO_TAP:
                    taps, boosters = await self.get_taps(http_client=http_client)
                    if taps != 0:
                        if boosters != 0:
                            status = await self.use_booster(http_client)
                            if status:
                                logger.success(f"<light-yellow>{self.session_name}</light-yellow> | Used booster")

                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | You have {taps} taps "
                                    f"available, starting clicking, please wait a bit..")
                        status = await self.do_taps(http_client=http_client, taps=taps)
                        if status:
                            logger.success(f"<light-yellow>{self.session_name}</light-yellow> | Successfully tapped "
                                           f"{taps} times")
                        else:
                            logger.warning(f"<light-yellow>{self.session_name}</light-yellow> | Problem with taps")

                if settings.AUTO_MISSION:
                    missions = await self.get_missions(http_client=http_client)
                    if missions is None:
                        continue
                    missions.sort()
                    for id in missions:
                        status = await self.do_mission(http_client=http_client, id=id)
                        if status:
                            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                        f"Successfully done mission {id}")
                        await asyncio.sleep(5)

                if settings.AUTO_LVL_UP:
                    info = await self.get_balance(http_client=http_client)
                    balance = info.get("balance") or 0
                    lvl, available, price, new_lvl = await self.get_level_info(http_client=http_client)
                    if available and price <= balance:
                        if new_lvl:
                            status = await self.level_up(http_client=http_client)
                            if status:
                                logger.success(f"<light-yellow>{self.session_name}</light-yellow> | "
                                               f"Successfully level up, now {new_lvl} lvl available")
                        else:
                            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | You reached max lvl - 25")

                if settings.PLAY_WALK_GAME:
                    status = await self.play_game_1(http_client=http_client)
                    if status:
                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"Successfully played walk game")
                    else:
                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"Walk game cooldown")

                if settings.PLAY_SHOOT_GAME:
                    status = await self.play_game_2(http_client=http_client)
                    if status:
                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"Successfully played shoot game")
                    else:
                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"Shoot game cooldown")

                if settings.PLAY_RPG_GAME:
                    status = await self.play_game_5(http_client=http_client)
                    if status:
                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"Successfully played RPG game")
                    else:
                        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | "
                                    f"RPG game cooldown")

                if settings.PLAY_DIRTY_JOB_GAME:
                    await self.play_game_3(http_client=http_client)

                if settings.PLAY_HURTMEPLEASE_GAME:
                    await self.play_game_6(http_client=http_client)

                logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Going sleep 1,5 hour")

                await asyncio.sleep(5400)

            except InvalidSession as error:
                raise error

            except Exception as error:
                logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Unknown error: {error}")
                await asyncio.sleep(delay=600)
                continue


async def run_tapper(tg_client: Client, proxy: str | None, start_sleep: int):
    try:
        logger.warning(f"{tg_client.name} | Start sleep <c>{start_sleep:,}</c> sec.")
        await asyncio.sleep(start_sleep)

        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
