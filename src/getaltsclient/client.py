import asyncio
import inspect
import json
import logging
from asyncio import AbstractEventLoop
from datetime import datetime
from datetime import timedelta
from enum import Enum
from typing import Dict, Callable, Coroutine, Any

import aiohttp

try:
    from dataclasses import dataclass
except ImportError:
    print("You need to either use Python 3.7 or pip install the 'dataclasses' package.")
    import sys

    sys.exit()


class Service(Enum):
    Microsoft = "ms"
    Google = "go"
    GMail = "gm"
    Yahoo = "yh"
    LinkedIN = "ln"
    Uber = "ub"
    WeChat = "wc"
    Instagram = "ig"
    LineMessenger = "lm"
    Telegram = "tg"
    VkCom = "vk"
    YouTube = "yt"
    Facebook = "fb"
    Steam = "st"
    Yandex = "ya"
    Whatsapp = "wp"
    Tinder = "ti"
    Twitter = "tw"
    AnyOther = "ot"


class Country(Enum):
    Russia = "ru"
    Ukraine = "ua"
    Kazakhstan = "kz"
    China = "cn"
    Philippines = "ph"
    Myanmar = "mm"
    Indonesia = "id"
    Malaysia = "my"
    Kenya = "ke"
    Tanzania = "tz"
    Vietnam = "vn"
    Kyrgyzstan = "kg"
    USA = "us"
    Israel = "il"
    HongKong = "hk"
    Poland = "pl"
    UnitedKingdom = "uk"
    Madagascar = "mg"
    Congo = "cg"
    Nigeria = "ng"
    Macau = "mo"
    Egypt = "eg"
    Ireland = "ie"
    Cambodia = "kh"
    Lao = "la"
    Haiti = "ht"
    IvoryCoast = "ci"
    Gambia = "gm"
    Serbian = "rs"
    Yemen = "ye"
    SouthAfrica = "za"
    Romania = "ro"
    Estonia = "ee"
    Azerbaijan = "az"
    Canada = "ca"
    Morocco = "ma"
    Ghana = "gh"
    Argentina = "ar"
    Uzbekistan = "uz"
    Cameroon = "cm"
    Chad = "tg"
    Germany = "de"
    Lithuania = "lt"
    Croatia = "hr"
    Iraq = "iq"
    Netherlands = "nl"
    India = "in"


class Status(Enum):
    """
    Enumeration of statuses that GetAlts will provide depending on the current state of activation.
    See https://telegra.ph/List-of-available-statuses-06-09
    """

    Ready = "READY"
    AccessReady = "ACCESS_READY"
    WaitingForCode = "STATUS_WAIT_CODE"
    Cancelled = "ACCESS_CANCEL"
    AccessConfirmGet = "ACCESS_CONFIRM_GET"
    StatusOk = "STATUS_OK"


class _Action(Enum):
    SendSMS = "SMS_SENT"
    Cancel = "CANCEL"
    End = "END"
    SendAnotherCode = "ONE_MORE_CODE"
    AlreadyUsed = "ALREADY_USED"


@dataclass(init=True, repr=True)
class ActivationContext:
    phone_number: str
    activation_id: int
    status: Status
    code: int = None

    @classmethod
    def _from_dict(cls, data: Dict):
        return ActivationContext(
            phone_number=data["phone_number"],
            activation_id=data["activation_id"],
            status=Status(data["status"]),
        )


class GetAltsAPIError(Exception):
    pass


class NoCodeReceived(Exception):
    pass


class GetAltsClient:
    base_url = "http://getalts.club/api"

    def __init__(self, token: str, loop: AbstractEventLoop = None, timeout: int = 10):
        self.token = token
        self.loop = loop or asyncio.get_event_loop()
        self.timeout = aiohttp.ClientTimeout(timeout)
        self.log = logging.getLogger(GetAltsClient.__name__)
        self.log.addHandler(logging.NullHandler())

    def _endpoint(self, name: str):
        return f"{self.base_url}/{name}"

    async def get_balance(self) -> float:
        response = await self._get("get_balance")
        return response["balance"]

    async def get_available_numbers_count(self, country: Country) -> Dict:
        response = await self._get("get_amount", dict(country=country.value))
        return {Service(k): v for k, v in response.items()}

    async def get_prices_by_country(self, country: Country) -> Dict:
        response = await self._get("get_prices_by_country", dict(country=country.value))
        return {Service(k): v for k, v in response.items()}

    async def get_prices_by_service(self, service: Service) -> Dict:
        response = await self._get("get_prices_by_service", dict(service=service.value))
        return {Country(k): v for k, v in response.items()}

    async def buy_number(self, service: Service, country: Country) -> ActivationContext:
        response = await self._get(
            "buy_number", dict(service=service.value, country=country.value)
        )
        return ActivationContext._from_dict(response)

    async def register_code_received_callback(
        self,
        callback: Callable[[ActivationContext], None] or Coroutine[Any, Any, None],
        for_context: ActivationContext,
        max_wait: timedelta = timedelta(minutes=1)
    ):
        context = for_context
        start = datetime.now()
        while True:
            if datetime.now() > start + max_wait:
                raise NoCodeReceived

            self.log.info("Checking activation status for code...")

            context = await self.get_activation_status(context)
            if context.code is not None:
                break
            await asyncio.sleep(5)

        if inspect.iscoroutinefunction(callback):
            await callback(context)
        else:
            callback(context)

    async def _notify_code_received(self,
                                    callback: Callable[[ActivationContext], None],
                                    for_context: ActivationContext,
                                    ):
        pass

    async def get_activation_status(
        self, activation_context: ActivationContext
    ) -> ActivationContext:
        response = await self._get(
            "get_activation_status",
            dict(activation_id=activation_context.activation_id),
        )
        return self.__context_from_response(activation_context, response)

    async def _set_activation_status(
        self, activation_context: ActivationContext, new_status: _Action
    ) -> ActivationContext:
        response = await self._get(
            "set_activation_status",
            dict(
                activation_id=activation_context.activation_id,
                status=new_status.value.lower(),  # TODO: This is a bug in the API, it should not be case sensitive.
            ),
        )
        return self.__context_from_response(activation_context, response)

    async def cancel_activation(self, activation_context: ActivationContext):
        """
        Tries to cancel the activation. If this is not allowed with the current status, it will mark the number
        as already used (which will automatically refund the money to your account).
        """
        try:
            return await self._set_activation_status(activation_context, _Action.Cancel)
        except GetAltsAPIError:
            self.log.info(
                "Cancelling activation not possible, marking number as already used instead."
            )
            return await self.mark_number_as_already_used(activation_context)

    async def set_ready_for_code(self, activation_context: ActivationContext):
        return await self._set_activation_status(activation_context, _Action.SendSMS)

    async def end_activation(self, activation_context: ActivationContext):
        return await self._set_activation_status(activation_context, _Action.End)

    async def send_another_code(self, activation_context: ActivationContext):
        return await self._set_activation_status(
            activation_context, _Action.SendAnotherCode
        )

    async def mark_number_as_already_used(self, activation_context: ActivationContext):
        return await self._set_activation_status(
            activation_context, _Action.AlreadyUsed
        )

    @staticmethod
    def __context_from_response(
        old_context: ActivationContext, response: Dict
    ) -> ActivationContext:
        old_context.status = Status(response["status"])
        old_context.code = response.get("code", None)
        return old_context

    async def _get(self, endpoint: str, query_params: Dict = None) -> Dict:
        self.log.debug(
            f"Making request to {endpoint} with parameters {query_params} ..."
        )
        params = query_params or dict()
        params.update(token=self.token)

        url = self._endpoint(endpoint)

        async with aiohttp.ClientSession(
            loop=self.loop, timeout=self.timeout
        ) as session:  # type: aiohttp.ClientSession
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                result = json.loads(await response.text("utf-8"))
                if "error" in result:
                    raise GetAltsAPIError(result["error"])
                self.log.debug(f"Received response: {result}")
                return result
