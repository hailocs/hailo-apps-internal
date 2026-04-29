"""VelocityCommand has 3 axes after the orbit feature was removed."""

import inspect
from dataclasses import fields

from drone_follow.follow_api import VelocityCommand


def test_velocity_command_has_three_fields():
    names = {f.name for f in fields(VelocityCommand)}
    assert names == {"forward_m_s", "down_m_s", "yawspeed_deg_s"}


def test_velocity_command_constructor_takes_three_args():
    cmd = VelocityCommand(1.0, -0.5, 30.0)
    assert cmd.forward_m_s == 1.0
    assert cmd.down_m_s == -0.5
    assert cmd.yawspeed_deg_s == 30.0
