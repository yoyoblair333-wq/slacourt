"""Direct-mode helpers: real GenVM SDK in-process, web + LLM mocked by regex."""

import os
import sys

import pytest

GENVM_VERSION = os.environ.get("GENVM_VERSION") or "v0.2.16"


@pytest.fixture
def direct_deploy(direct_deploy):
    def _deploy(contract_path, *args, sdk_version=None, **kwargs):
        return direct_deploy(contract_path, *args, sdk_version=sdk_version or GENVM_VERSION, **kwargs)
    return _deploy


def set_tx_time(vm, ts: str) -> None:
    # gltest 0.29 direct mode: warp() does not refresh gl.message_raw['datetime'].
    vm.warp(ts)
    sys.modules["genlayer.gl"].message_raw["datetime"] = ts
