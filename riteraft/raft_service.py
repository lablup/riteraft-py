import asyncio
import logging
import pickle
from asyncio import Queue

import grpc

from riteraft.message import (
    MessageConfigChange,
    MessageRaft,
    MessageRequestId,
    RaftRespError,
    RaftRespIdReserved,
    RaftRespJoinSuccess,
    RaftRespOk,
    RaftRespWrongLeader,
)
from riteraft.protos import eraftpb_pb2, raft_service_pb2


class RaftService:
    def __init__(self, sender: Queue) -> None:
        self.sender = sender

    async def RequestId(
        self, request: raft_service_pb2.RequestIdArgs, context: grpc.aio.ServicerContext
    ) -> raft_service_pb2.IdRequestResponse:
        chan = Queue()
        addr = request.addr

        try:
            await self.sender.put(MessageRequestId(addr, chan))
        except Exception:
            pass

        response = await chan.get()

        if isinstance(response, RaftRespWrongLeader):
            logging.warning("Sending wrong leader")
            leader_id, leader_addr = response.leader_id, response.leader_addr

            return raft_service_pb2.IdRequestResponse(
                code=raft_service_pb2.WrongLeader,
                data=pickle.dumps(tuple([leader_id, leader_addr, None])),
            )
        elif isinstance(response, RaftRespIdReserved):
            reserved_id = response.reserved_id
            peer_addrs = response.peer_addrs
            leader_id = response.leader_id

            return raft_service_pb2.IdRequestResponse(
                code=raft_service_pb2.Ok,
                data=pickle.dumps(tuple([leader_id, reserved_id, peer_addrs])),
            )
        else:
            assert False, "Unreachable"

    async def ChangeConfig(
        self, request: eraftpb_pb2.ConfChange, context: grpc.aio.ServicerContext
    ) -> raft_service_pb2.RaftResponse:
        chan = Queue()
        await self.sender.put(MessageConfigChange(request, chan))
        reply = raft_service_pb2.RaftResponse()

        try:
            if raft_response := await asyncio.wait_for(chan.get(), 2):
                if isinstance(raft_response, RaftRespOk) or isinstance(
                    raft_response, RaftRespJoinSuccess
                ):
                    reply.inner = raft_response.encode()

        except asyncio.TimeoutError:
            reply.inner = RaftRespError().encode()
            logging.error("Timeout waiting for reply")

        finally:
            return reply

    async def SendMessage(
        self, request: eraftpb_pb2.Message, context: grpc.aio.ServicerContext
    ) -> raft_service_pb2.RaftResponse:
        await self.sender.put(MessageRaft(request))
        return raft_service_pb2.RaftResponse(inner=RaftRespOk().encode())
