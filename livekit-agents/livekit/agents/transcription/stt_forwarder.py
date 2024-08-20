from __future__ import annotations

import asyncio
import json
import contextlib
from typing import Optional

from livekit import rtc

from ..rtc import TranscriptionSegment


from .. import stt
from ..log import logger
from . import _utils


class STTSegmentsForwarder:
    """
    Forward STT transcription to the users. (Useful for client-side rendering)
    """

    def __init__(
        self,
        *,
        room: rtc.Room,
        participant: rtc.Participant | str,
        track: rtc.Track | rtc.TrackPublication | str | None = None,
    ):
        identity = participant if isinstance(participant, str) else participant.identity
        if track is None:
            track = _utils.find_micro_track_id(room, identity)
        elif isinstance(track, (rtc.TrackPublication, rtc.Track)):
            track = track.sid

        self._room = room
        self._participant_identity = identity
        self._track_id = track
        self._queue = asyncio.Queue[Optional[TranscriptionSegment]]()
        self._main_task = asyncio.create_task(self._run())
        self._current_id = _utils.segment_uuid()

    async def _run(self):
        try:
            while True:
                seg = await self._queue.get()
                if seg is None:
                    break
                #transcription = rtc.Transcription(
                #    participant_identity=self._participant_identity,
                #    track_id=self._track_id,
                #    segments=[seg],  # no history for now
                #    language="",  # TODO(theomonnom)
                #)
                #class TranscriptionSegment:
                #id: str
                #text: str
                #start_time: int
                #end_time: int
                #final: bool
                language = self._room.metadata
                print('language')
                print(language)
                transcription_json = {
                    "type": "transcription",
                    "id": seg.id,
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                    "is_final": seg.final,
                    "language": language,
                    "speaker": seg.speaker,
                    "text": seg.text,
                }
                logger.debug("forwarding transcription: %s", transcription_json)
                #Get all participants in the room and send to them
                participants = self._room.participants
                destination_sids = []
                for participant in participants:
                    #test if participant is str
                    if isinstance(participant, str):
                        destination_sids.append(participant)
                    else:
                        destination_sids.append(participant.sid)
                #Publish the transcription to all participants in the room
                await self._room.local_participant.publish_data(payload=json.dumps(transcription_json).encode('utf-8'), destination_sids=destination_sids) # .publish_transcription(transcription)

        except Exception:
            logger.exception("error in stt transcription")

    def update(self, ev: stt.SpeechEvent):
        if ev.type == stt.SpeechEventType.INTERIM_TRANSCRIPT:
            # TODO(theomonnom): We always take the first alternative, we should mb expose opt to the
            # user?
            text = ev.alternatives[0].text
            self._queue.put_nowait(
                TranscriptionSegment(
                    id=self._current_id,
                    text=text,
                    start_time=0,
                    end_time=0,
                    final=False,
                    speaker=ev.alternatives[0].speaker,
                )
            )
        elif ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
            text = ev.alternatives[0].text
            self._queue.put_nowait(
                TranscriptionSegment(
                    id=self._current_id,
                    text=text,
                    start_time=0,
                    end_time=0,
                    final=True,
                    speaker=ev.alternatives[0].speaker,
                )
            )

            self._current_id = _utils.segment_uuid()

    async def aclose(self, *, wait: bool = True) -> None:
        self._queue.put_nowait(None)

        if not wait:
            self._main_task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await self._main_task
