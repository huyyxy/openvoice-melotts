from . import cleaned_text_to_sequence
import copy

# 语言模块缓存，避免重复导入
_language_module_cache = {}


def _get_language_module(language):
    """动态导入语言模块，只在需要时加载"""
    if language in _language_module_cache:
        return _language_module_cache[language]
    
    # 动态导入对应的语言模块
    if language == "ZH":
        from . import chinese
        module = chinese
    elif language == "JP":
        from . import japanese
        module = japanese
    elif language == "EN":
        from . import english
        module = english
    elif language == "ZH_MIX_EN":
        from . import chinese_mix
        module = chinese_mix
    elif language == "KR":
        from . import korean
        module = korean
    elif language == "FR":
        from . import french
        module = french
    elif language in ("SP", "ES"):
        from . import spanish
        module = spanish
    else:
        raise ValueError(f"Unsupported language: {language}")
    
    # 缓存模块
    _language_module_cache[language] = module
    return module


def clean_text(text, language):
    language_module = _get_language_module(language)
    norm_text = language_module.text_normalize(text)
    phones, tones, word2ph = language_module.g2p(norm_text)
    return norm_text, phones, tones, word2ph


def clean_text_bert(text, language, device=None):
    language_module = _get_language_module(language)
    norm_text = language_module.text_normalize(text)
    phones, tones, word2ph = language_module.g2p(norm_text)
    
    word2ph_bak = copy.deepcopy(word2ph)
    for i in range(len(word2ph)):
        word2ph[i] = word2ph[i] * 2
    word2ph[0] += 1
    bert = language_module.get_bert_feature(norm_text, word2ph, device=device)
    
    return norm_text, phones, tones, word2ph_bak, bert


def text_to_sequence(text, language):
    norm_text, phones, tones, word2ph = clean_text(text, language)
    return cleaned_text_to_sequence(phones, tones, language)


if __name__ == "__main__":
    pass