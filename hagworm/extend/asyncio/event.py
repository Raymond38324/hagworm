# -*- coding: utf-8 -*-

from aioredis.pubsub import Receiver

from hagworm.extend.event import EventDispatcher
from hagworm.extend.asyncio.base import Utils, AsyncCirculator, AsyncFuncWrapper, FutureWithTimeout


class DistributedEvent(EventDispatcher):

    def __init__(self, redis_pool, channel_name, channel_count):

        super().__init__()

        self._redis_pool = redis_pool

        self._channels = [
            r'event_bus_{0}_{1}'.format(
                Utils.md5_u32(channel_name),
                channel
            )
            for channel in range(channel_count)
        ]

        for channel in self._channels:
            Utils.ensure_future(self._event_listener(channel))

    async def _event_listener(self, channel):

        async for _ in AsyncCirculator():

            async with self._redis_pool.get_client() as cache:

                receiver = Receiver()

                await cache.subscribe(
                    receiver.channel(channel)
                )

                async for channel, message in receiver.iter():
                    await self._event_assigner(channel, message)

    async def _event_assigner(self, channel, message):

        message = Utils.pickle_loads(message)

        Utils.log.debug(r'event handling => channel({0}) message({1})'.format(channel.name.decode(), message))

        _type = message.get(r'type', r'')
        args = message.get(r'args', [])
        kwargs = message.get(r'kwargs', {})

        if _type in self._observers:
            await self._observers[_type](*args, **kwargs)

    def _gen_observer(self):

        return AsyncFuncWrapper()

    async def dispatch(self, _type, *args, **kwargs):

        channel = self._channels[Utils.md5_u32(_type) % len(self._channels)]

        message = {
            r'type': _type,
            r'args': args,
            r'kwargs': kwargs,
        }

        Utils.log.debug(r'event dispatch => channel({0}) message({1})'.format(channel, message))

        async with self._redis_pool.get_client() as cache:
            await cache.publish(channel, Utils.pickle_dumps(message))

    def gen_event_waiter(self, event_type, delay_time):

        return EventWaiter(self, event_type, delay_time)


class EventWaiter(FutureWithTimeout):

    def __init__(self, dispatcher, event_type, delay_time):

        super().__init__(delay_time)

        self._dispatcher = dispatcher
        self._event_type = event_type

        self._dispatcher.add_listener(self._event_type, self._event_handler)

    def set_result(self, result):

        if self.done():
            return

        super().set_result(result)

        self._dispatcher.remove_listener(self._event_type, self._event_handler)

    def _event_handler(self, *args, **kwargs):

        if self.done():
            return

        self.set_result({r'args': args, r'kwargs': kwargs})
