# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import requests

from os.path import join, dirname
from time import time
from typing import List
from ovos_plugin_common_play import MediaType, PlaybackType
from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill, \
    ocp_search
from ovos_utils.log import LOG
from pyradios.base_url import fetch_hosts
from lingua_franca.parse import extract_langcode
from lingua_franca import load_language


class InternetRadioSkill(OVOSCommonPlaybackSkill):
    def __init__(self):
        super(InternetRadioSkill, self).__init__()
        self.supported_media = [MediaType.MUSIC,
                                MediaType.AUDIO,
                                MediaType.RADIO,
                                MediaType.GENERIC]
        self._candidate_hosts = list(set([f"https://{host}" for
                                     host in fetch_hosts()]))
        self._headers = {"User-Agent": "neon.ai/skill-internet_radio"}
        LOG.info(f"Got candidates: {self._candidate_hosts}")
        self._host_url = None
        self._stations = None
        self._image_url = join(dirname(__file__), 'ui/radio-solid.svg')
        self._max_results = 50

    @property
    def host_url(self) -> str:
        timeout = time() + 5
        while not self._host_url and time() < timeout:
            LOG.info("Selecting Candidate")
            candidate = self._candidate_hosts[0]
            LOG.info(f"Testing {candidate}")
            try:
                if requests.get(candidate, timeout=2, headers=self._headers).ok:
                    LOG.info(f"Candidate ok: {candidate}")
                    self._host_url = candidate
                else:
                    LOG.warning(f"Removing broken host: {candidate}")
                    self._candidate_hosts.remove(candidate)
            except TimeoutError:
                LOG.warning(f"{candidate} timed out")
                self._candidate_hosts.remove(candidate)
        return self._host_url

    @property
    def country_code(self) -> str:
        return self.location['city']['state']['country']['code'] or "US"

    @property
    def language(self) -> str:
        return self.lang.split('-')[0]

    @property
    def stations(self) -> List[dict]:
        if not self._host_url:
            LOG.info(f"Initializing Host URL")
            LOG.info(self.host_url)
        timeout = time() + 30
        while not self._stations and time() < timeout:
            try:
                LOG.info("Updating stations list")
                resp = requests.get(f"{self.host_url}/json/stations",
                                    timeout=(3, 3), headers=self._headers)
                if resp.ok:
                    stations = resp.json()
                else:
                    LOG.info(f"Request returned: {resp.status_code}")
                    stations = None
                if stations and self._validate_stations(stations):
                    self._stations = stations
                    LOG.info(f"Found {len(self._stations)} stations")
                else:
                    LOG.error(f"Broken stations listing retrieved, try again")
                    self._stations = None
                    self._candidate_hosts.remove(self.host_url)
                    self._host_url = None
            except Exception as e:
                LOG.exception(e)
                self._candidate_hosts.remove(self.host_url)
                self._host_url = None
        if not self._stations and time() > timeout:
            raise TimeoutError("Timed out getting stations listing!")
        return self._stations

    def initialize(self):
        try:
            stations = self.stations
            LOG.info(f"Found {len(stations)} stations")
        except TimeoutError:
            LOG.error(f"Timed out updating stations")

    @staticmethod
    def _validate_stations(stations: list):
        """
        Sanity check return to make sure we got language codes in the return
        :param stations: list of stations from the API
        """
        return any((station for station in stations if
                    "en" in station.get('languagecodes')))

    @ocp_search()
    def search_music(self, phrase, media_type=MediaType.GENERIC):
        base_confidence = 0
        if media_type == MediaType.RADIO:
            base_confidence += 50
        elif media_type == MediaType.MUSIC:
            base_confidence += 40
        elif media_type == MediaType.AUDIO:
            base_confidence += 30

        lang_params = self.parse_request_locale(phrase)
        candidates = self._get_local_stations(**lang_params)
        if self.voc_match("internet"):
            base_confidence += 20
        matches = self._get_candidate_matches(candidates,
                                              phrase, base_confidence)
        if len(matches) > self._max_results:
            matches = matches[:self._max_results]
        return matches

    def _get_candidate_matches(self, candidates: List[dict], phrase: str,
                               base_confidence: int = 0):
        matches = []
        for candidate in candidates:
            if candidate['name'].lower() in phrase.lower():
                confidence = base_confidence + 50
                LOG.debug(f"Name match: {candidate['name']}")
            elif candidate.get('tags') and any((tag in phrase for tag in
                                                candidate['tags'].split(','))):
                # TODO: Better confidence based on number of tags
                confidence = base_confidence + 20
                LOG.debug(f"Tag match: {candidate['name']} "
                          f"(tags={candidate['tags']})")

            else:
                confidence = base_confidence
            if confidence >= 50:  # Don't bother with low confidence matches
                matches.append({
                    "media_type": MediaType.RADIO,
                    "playback": PlaybackType.AUDIO,
                    "image": candidate.get("favicon"),
                    "skill_icon": self._image_url,
                    "uri": candidate.get("url"),
                    "title": candidate.get("name"),
                    "match_confidence": confidence
                })
        matches.sort(key=lambda station: station.get('match_confidence'),
                     reverse=True)
        LOG.info(f"Found {len(matches)} matches for: {phrase}")
        return matches

    def _get_local_stations(self, lang: str, country: str):
        """
        Get all stations in the requested language and country
        """
        LOG.info("get_local_stations")
        return [s for s in self.stations if lang.lower()
                in s['languagecodes'].lower() and
                s['countrycode'].lower() == country.lower()]

    def parse_request_locale(self, phrase) -> dict:
        """
        Get a language and country from a playback request.
        """
        load_language(self.lang)
        extracted = extract_langcode(phrase)
        lang = extracted[0] if extracted and extracted[1] > 0.9 else self.language
        country = self.country_code
        # TODO: Extract requested country
        return {'lang': lang,
                'country': country}


def create_skill():
    return InternetRadioSkill()
