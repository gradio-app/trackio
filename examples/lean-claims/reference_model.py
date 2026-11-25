"""The hand-written model the code generator replaced.

`check_generated.py` copies identical weights into this model and into the model
generated from `Model.lean`, and checks that they compute the same thing. Training
does not use this file.
"""

import math

import torch
import torch.nn.functional as F
from torch import nn

PAD, BOS, EOS = 0, 1, 2


def causal_mask(length, device):
    return torch.ones(length, length, dtype=torch.bool, device=device).tril()


class MultiHeadAttention(nn.Module):
    def __init__(self, d_model, h, d_k, d_v):
        super().__init__()
        self.h, self.d_k, self.d_v = h, d_k, d_v
        self.w_q = nn.Linear(d_model, h * d_k, bias=False)
        self.w_k = nn.Linear(d_model, h * d_k, bias=False)
        self.w_v = nn.Linear(d_model, h * d_v, bias=False)
        self.w_o = nn.Linear(h * d_v, d_model, bias=False)

    def forward(self, x, memory, mask):
        b, lq, _ = x.shape
        lk = memory.shape[1]
        q = self.w_q(x).view(b, lq, self.h, self.d_k).transpose(1, 2)
        k = self.w_k(memory).view(b, lk, self.h, self.d_k).transpose(1, 2)
        v = self.w_v(memory).view(b, lk, self.h, self.d_v).transpose(1, 2)
        out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.w_o(out.transpose(1, 2).reshape(b, lq, self.h * self.d_v))


class FeedForward(nn.Module):
    def __init__(self, d_model, d_ff):
        super().__init__()
        self.w_1 = nn.Linear(d_model, d_ff)
        self.w_2 = nn.Linear(d_ff, d_model)

    def forward(self, x):
        return self.w_2(F.relu(self.w_1(x)))


class EncoderLayer(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.attn = MultiHeadAttention(c["d_model"], c["h"], c["d_k"], c["d_v"])
        self.ffn = FeedForward(c["d_model"], c["d_ff"])
        self.norm1 = nn.LayerNorm(c["d_model"])
        self.norm2 = nn.LayerNorm(c["d_model"])
        self.drop = nn.Dropout(c["p_drop"])

    def forward(self, x, mask):
        x = self.norm1(x + self.drop(self.attn(x, x, mask)))
        return self.norm2(x + self.drop(self.ffn(x)))


class DecoderLayer(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.self_attn = MultiHeadAttention(c["d_model"], c["h"], c["d_k"], c["d_v"])
        self.cross_attn = MultiHeadAttention(c["d_model"], c["h"], c["d_k"], c["d_v"])
        self.ffn = FeedForward(c["d_model"], c["d_ff"])
        self.norm1 = nn.LayerNorm(c["d_model"])
        self.norm2 = nn.LayerNorm(c["d_model"])
        self.norm3 = nn.LayerNorm(c["d_model"])
        self.drop = nn.Dropout(c["p_drop"])

    def forward(self, y, memory, self_mask, cross_mask):
        y = self.norm1(y + self.drop(self.self_attn(y, y, self_mask)))
        y = self.norm2(y + self.drop(self.cross_attn(y, memory, cross_mask)))
        return self.norm3(y + self.drop(self.ffn(y)))


class Transformer(nn.Module):
    def __init__(self, c, vocab_size):
        super().__init__()
        self.d_model = c["d_model"]
        self.embed = nn.Embedding(vocab_size, c["d_model"], padding_idx=PAD)
        nn.init.normal_(self.embed.weight, std=c["d_model"] ** -0.5)
        self.encoder = nn.ModuleList(EncoderLayer(c) for _ in range(c["N"]))
        self.decoder = nn.ModuleList(DecoderLayer(c) for _ in range(c["N"]))
        self.drop = nn.Dropout(c["p_drop"])
        positions = torch.arange(512).unsqueeze(1)
        freqs = torch.exp(
            torch.arange(0, c["d_model"], 2) * (-math.log(10000.0) / c["d_model"])
        )
        pe = torch.zeros(512, c["d_model"])
        pe[:, 0::2] = torch.sin(positions * freqs)
        pe[:, 1::2] = torch.cos(positions * freqs)
        self.register_buffer("pe", pe, persistent=False)

    def embed_tokens(self, ids):
        x = self.embed(ids) * math.sqrt(self.d_model)
        return self.drop(x + self.pe[: ids.shape[1]])

    def encode(self, src):
        mask = (src != PAD)[:, None, None, :]
        x = self.embed_tokens(src)
        for layer in self.encoder:
            x = layer(x, mask)
        return x, mask

    def decode(self, tgt, memory, src_mask):
        length = tgt.shape[1]
        causal = causal_mask(length, tgt.device)
        y = self.embed_tokens(tgt)
        for layer in self.decoder:
            y = layer(y, memory, causal[None, None], src_mask)
        return y @ self.embed.weight.T

    def forward(self, src, tgt_in):
        memory, src_mask = self.encode(src)
        return self.decode(tgt_in, memory, src_mask)

    @torch.no_grad()
    def greedy(self, src, max_extra: int = 50):
        memory, src_mask = self.encode(src)
        out = torch.full((src.shape[0], 1), BOS, dtype=torch.long, device=src.device)
        done = torch.zeros(src.shape[0], dtype=torch.bool, device=src.device)
        for _ in range(src.shape[1] + max_extra):
            next_id = self.decode(out, memory, src_mask)[:, -1].argmax(-1)
            next_id = torch.where(done, torch.full_like(next_id, PAD), next_id)
            out = torch.cat([out, next_id[:, None]], dim=1)
            done |= next_id == EOS
            if done.all():
                break
        return out[:, 1:]
