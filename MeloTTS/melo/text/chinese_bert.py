import os
import torch
import sys
from transformers import AutoTokenizer, AutoModelForMaskedLM


# model_id = 'hfl/chinese-roberta-wwm-ext-large'
local_path = "./bert/chinese-roberta-wwm-ext-large"


tokenizers = {}
models = {}

def get_bert_feature(text, word2ph, device=None, model_id='hfl/chinese-roberta-wwm-ext-large', model_path=None):
    # 离线/ Docker：优先从本地路径加载，避免 HuggingFace 联网
    use_local = (
        model_path is not None
        and os.path.isdir(model_path)
        and os.path.isfile(os.path.join(model_path, "config.json"))
    )
    load_key = model_path if use_local else model_id

    if load_key not in models:
        if use_local:
            models[load_key] = AutoModelForMaskedLM.from_pretrained(
                model_path, local_files_only=True
            ).to(device)
            tokenizers[load_key] = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        else:
            models[load_key] = AutoModelForMaskedLM.from_pretrained(model_id).to(device)
            tokenizers[load_key] = AutoTokenizer.from_pretrained(model_id)
    model = models[load_key]
    tokenizer = tokenizers[load_key]

    if (
        sys.platform == "darwin"
        and torch.backends.mps.is_available()
        and device == "cpu"
    ):
        device = "mps"
    if not device:
        device = "cuda"

    with torch.no_grad():
        inputs = tokenizer(text, return_tensors="pt")
        for i in inputs:
            inputs[i] = inputs[i].to(device)
        res = model(**inputs, output_hidden_states=True)
        res = torch.cat(res["hidden_states"][-3:-2], -1)[0].cpu()
    # import pdb; pdb.set_trace()
    # assert len(word2ph) == len(text) + 2
    word2phone = word2ph
    phone_level_feature = []
    for i in range(len(word2phone)):
        repeat_feature = res[i].repeat(word2phone[i], 1)
        phone_level_feature.append(repeat_feature)

    phone_level_feature = torch.cat(phone_level_feature, dim=0)
    return phone_level_feature.T


if __name__ == "__main__":
    import torch

    word_level_feature = torch.rand(38, 1024)  # 12个词,每个词1024维特征
    word2phone = [
        1,
        2,
        1,
        2,
        2,
        1,
        2,
        2,
        1,
        2,
        2,
        1,
        2,
        2,
        2,
        2,
        2,
        1,
        1,
        2,
        2,
        1,
        2,
        2,
        2,
        2,
        1,
        2,
        2,
        2,
        2,
        2,
        1,
        2,
        2,
        2,
        2,
        1,
    ]

    # 计算总帧数
    total_frames = sum(word2phone)
    print(word_level_feature.shape)
    print(word2phone)
    phone_level_feature = []
    for i in range(len(word2phone)):
        print(word_level_feature[i].shape)

        # 对每个词重复word2phone[i]次
        repeat_feature = word_level_feature[i].repeat(word2phone[i], 1)
        phone_level_feature.append(repeat_feature)

    phone_level_feature = torch.cat(phone_level_feature, dim=0)
    print(phone_level_feature.shape)  # torch.Size([36, 1024])
