import math

import pytest
import torch

from nanogpt_lib.model import GPT, GPTConfig
from nanogpt_lib.train import get_lr


def cfg(**kw):
    d = dict(vocab_size=50, block_size=16, n_layer=2, n_head=2, n_embd=32, dropout=0.0)
    d.update(kw)
    return GPTConfig(**d)


def test_R4_shapes_and_no_bias_and_tying():
    m = GPT(cfg())
    x = torch.randint(0, 50, (3, 10))
    logits, loss = m(x)
    assert logits.shape == (3, 10, 50) and loss is None
    assert m.lm_head.weight is m.wte.weight
    assert not any(n.endswith("bias") for n, _ in m.named_parameters())
    assert len(m.blocks) == 2 and m.blocks[0].mlp.c_fc.out_features == 128


def test_R4_n_params_excludes_position_embeddings():
    c = cfg()
    m = GPT(c)
    d = c.n_embd
    per_block = 2 * d + 3 * d * d + d * d + 4 * d * d + 4 * d * d  # 2 LN + qkv + proj + fc + proj
    expected = c.vocab_size * d + c.n_layer * per_block + d
    assert m.num_params() == expected


def test_R4_bad_heads_and_too_long_sequence():
    with pytest.raises(ValueError):
        GPT(cfg(n_embd=30, n_head=4))
    with pytest.raises(ValueError):
        GPT(cfg())(torch.zeros(1, 17, dtype=torch.long))


def test_R5_init_stds():
    torch.manual_seed(0)
    m = GPT(cfg(n_embd=128, n_layer=4, n_head=4, vocab_size=200))
    assert m.wte.weight.std().item() == pytest.approx(0.02, rel=0.05)
    assert m.blocks[0].attn.c_attn.weight.std().item() == pytest.approx(0.02, rel=0.05)
    for b in m.blocks:
        for w in (b.attn.c_proj.weight, b.mlp.c_proj.weight):
            assert w.std().item() == pytest.approx(0.02 / math.sqrt(8), rel=0.05)


def test_R6_causal_masking():
    torch.manual_seed(0)
    m = GPT(cfg()).eval()
    x = torch.randint(0, 50, (2, 12))
    y = x.clone()
    y[:, 6:] = (y[:, 6:] + 7) % 50
    a, _ = m(x)
    b, _ = m(y)
    assert torch.allclose(a[:, :6], b[:, :6], atol=1e-6)
    assert not torch.allclose(a[:, 6:], b[:, 6:], atol=1e-6)


def test_R7_initial_loss_is_ln_vocab():
    torch.manual_seed(0)
    m = GPT(cfg(vocab_size=65, n_embd=64, n_head=4)).eval()
    x = torch.randint(0, 65, (16, 16))
    _, loss = m(x, torch.randint(0, 65, (16, 16)))
    assert loss.item() == pytest.approx(math.log(65), abs=0.05)


def test_R8_overfit_tiny_batch():
    torch.manual_seed(0)
    m = GPT(cfg(vocab_size=20, n_embd=32))
    x = torch.randint(0, 20, (4, 16))
    y = torch.randint(0, 20, (4, 16))
    opt = m.configure_optimizer(3e-3, 0.0, (0.9, 0.99))
    for _ in range(300):
        _, loss = m(x, y)
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert loss.item() < 0.05


def test_R9_weight_decay_groups():
    m = GPT(cfg())
    opt = m.configure_optimizer(1e-3, 0.1, (0.8, 0.95))
    dec, nodec = opt.param_groups
    assert dec["weight_decay"] == 0.1 and nodec["weight_decay"] == 0.0
    assert all(p.dim() >= 2 for p in dec["params"]) and all(p.dim() < 2 for p in nodec["params"])
    assert len(dec["params"]) + len(nodec["params"]) == len(list(m.parameters()))
    assert opt.param_groups[0]["betas"] == (0.8, 0.95)


def test_R10_lr_schedule_known_values():
    lr, mn, w, T = 1e-3, 1e-4, 10, 110
    assert get_lr(0, lr, mn, w, T) == pytest.approx(1e-4)           # 1/10 of lr
    assert get_lr(9, lr, mn, w, T) == pytest.approx(1e-3)           # end of warmup
    assert get_lr(10, lr, mn, w, T) == pytest.approx(1e-3)          # cosine start
    assert get_lr(60, lr, mn, w, T) == pytest.approx(5.5e-4)        # midpoint: min + 0.5*(lr-min)
    assert get_lr(110, lr, mn, w, T) == pytest.approx(1e-4)
    assert get_lr(500, lr, mn, w, T) == pytest.approx(1e-4)


def test_R17_generate_top_k_and_crop():
    torch.manual_seed(0)
    m = GPT(cfg(block_size=8))
    out = m.generate(torch.zeros(1, 3, dtype=torch.long), 30, top_k=1)  # longer than block_size
    assert out.shape == (1, 33)
    out2 = m.generate(torch.zeros(1, 3, dtype=torch.long), 30, top_k=1)
    assert torch.equal(out, out2)  # top-k=1 is greedy
