"""The network (Phase 4): one score, Q, for each (situation, option) pair.

DRRN-style (He et al. 2016, "Deep Reinforcement Learning with a Natural Language Action Space"): the situation
and each option are encoded apart, then a small head scores each pair. That fits a game whose options change
from one decision to the next (3 doors here, 40 items there). Q estimates the reward to come, discounted by the
game time until it comes (learn.py), if that option is picked now and play goes on as the network would play it.

Sizes are small on purpose (about 0.32 M weights, most in the token tables): it trains on the CPU while the game
runs and answers a decision in a few milliseconds.
"""

import numpy as np
import torch
from torch import nn

from . import features as F

HIDDEN, EMB, OUT = 128, 32, 64
SCALE = 100.0   # the network's output is Q in hundreds of points (the reward reaches -1000 at a death), a range Adam's
                # small steps reach; q_values and the training history give points


class QNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.s_tok = nn.EmbeddingBag(F.BUCKETS, EMB, mode="sum")
        self.a_tok = nn.EmbeddingBag(F.BUCKETS, EMB, mode="sum")
        for e in (self.s_tok, self.a_tok):
            nn.init.normal_(e.weight, std=0.05)
        self.s = nn.Sequential(nn.Linear(F.STATE_DIM + EMB, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, OUT), nn.ReLU())
        self.a = nn.Sequential(nn.Linear(F.OPTION_DIM + EMB, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, OUT), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(3 * OUT, 64), nn.ReLU(), nn.Linear(64, 1))

    def states(self, dense, toks, offs):
        return self.s(torch.cat([dense, self.s_tok(toks, offs)], 1))

    def options(self, dense, toks, offs):
        return self.a(torch.cat([dense, self.a_tok(toks, offs)], 1))

    def score(self, hs, seg, ha):
        """Q for each option row: hs are the situations, seg says which situation each option row belongs to."""
        h = hs[seg]
        return self.head(torch.cat([h, ha, h * ha], 1)).squeeze(1)


def ranges(starts, stops):
    """np.concatenate([np.arange(a, b) for a, b in zip(starts, stops)]), without the Python loop."""
    lens = stops - starts
    ends = np.cumsum(lens)
    return np.arange(ends[-1] if len(ends) else 0, dtype=np.int64) + np.repeat(starts - (ends - lens), lens)


class Pack:
    """Encoded rows (situations or options) as flat arrays: dense [n, dim], tokens flat, offsets [n]."""

    def __init__(self, dense, toks, offs):
        self.dense, self.toks, self.offs = dense, toks, offs

    @classmethod
    def of(cls, encoded, dim):
        dense = np.asarray([d for d, _ in encoded], dtype=np.float32).reshape(-1, dim)
        lens = [len(t) for _, t in encoded]
        offs = np.zeros(len(encoded), dtype=np.int64)
        if lens:
            offs[1:] = np.cumsum(lens)[:-1]
        toks = np.fromiter((x for _, t in encoded for x in t), dtype=np.int64, count=sum(lens))
        return cls(dense, toks, offs)

    def rows(self, idx):
        """The rows idx (a numpy int array) as tensors ready for the network."""
        idx = np.asarray(idx, dtype=np.int64)
        ends = np.append(self.offs[1:], len(self.toks))
        starts, stops = self.offs[idx], ends[idx]
        lens = stops - starts
        toks = self.toks[ranges(starts, stops)]
        offs = np.zeros(len(idx), dtype=np.int64)
        if len(idx):
            offs[1:] = np.cumsum(lens)[:-1]
        return torch.from_numpy(self.dense[idx]), torch.from_numpy(toks), torch.from_numpy(offs)


def q_values(net, msg):
    """Q for every option of one live decision request (a list of floats)."""
    options = msg.get("options") or []
    if not options:
        return []
    s = Pack.of([F.encode_state(msg)], F.STATE_DIM)
    a = Pack.of([F.encode_option(o, msg.get("obs")) for o in options], F.OPTION_DIM)
    with torch.no_grad():
        hs = net.states(*s.rows([0]))
        ha = net.options(*a.rows(np.arange(len(options))))
        q = net.score(hs, torch.zeros(len(options), dtype=torch.long), ha)
    return [SCALE * float(x) for x in q]


def save(net, path, **meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    torch.save({"version": F.VERSION, "state": net.state_dict(), **meta}, tmp)
    tmp.replace(path)


def load(path):
    """(network, metadata) or (None, None) if there is no usable saved network."""
    try:
        ck = torch.load(path, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, EOFError, ValueError):
        return None, None
    if ck.get("version") != F.VERSION:
        return None, None
    net = QNet()
    net.load_state_dict(ck["state"])
    net.eval()
    return net, {k: v for k, v in ck.items() if k != "state"}
