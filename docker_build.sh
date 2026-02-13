#!/usr/bin/env bash
# =============================================================================
# OpenVoice + MeloTTS Docker 离线构建脚本
# 所有模型在此脚本中下载，构建后的镜像运行时完全离线
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# 配置项（可按需修改）
# ---------------------------------------------------------------------------
IMAGE_NAME="${IMAGE_NAME:-openvoice-melo-tts}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# 要下载的 MeloTTS 语言（空格分隔，可选: ZH EN EN_V2 FR JP ES KR）
LANGUAGES="${LANGUAGES:-ZH}"

# 模型本地缓存目录（构建完成后可保留，下次构建免重复下载）
MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-./_model_cache}"

# NLTK 数据包列表
NLTK_PACKAGES="averaged_perceptron_tagger cmudict punkt stopwords wordnet"

# ---------------------------------------------------------------------------
# 语言 -> BERT 模型映射（兼容 bash 3.x）
# ---------------------------------------------------------------------------
get_bert_models() {
    case "$1" in
        ZH)    echo "hfl/chinese-roberta-wwm-ext-large bert-base-multilingual-uncased" ;;
        EN)    echo "bert-base-uncased" ;;
        EN_V2) echo "bert-base-uncased" ;;
        FR)    echo "dbmdz/bert-base-french-europeana-cased" ;;
        JP)    echo "tohoku-nlp/bert-base-japanese-v3" ;;
        ES)    echo "dccuchile/bert-base-spanish-wwm-uncased" ;;
        KR)    echo "kykim/bert-kor-base" ;;
        *)     return 1 ;;
    esac
}

# 语言 -> MeloTTS HuggingFace Repo 映射（兼容 bash 3.x）
get_melo_repo() {
    case "$1" in
        ZH)    echo "myshell-ai/MeloTTS-Chinese" ;;
        EN)    echo "myshell-ai/MeloTTS-English" ;;
        EN_V2) echo "myshell-ai/MeloTTS-English-v2" ;;
        FR)    echo "myshell-ai/MeloTTS-French" ;;
        JP)    echo "myshell-ai/MeloTTS-Japanese" ;;
        ES)    echo "myshell-ai/MeloTTS-Spanish" ;;
        KR)    echo "myshell-ai/MeloTTS-Korean" ;;
        *)     return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# 创建缓存目录
# ---------------------------------------------------------------------------
OPENVOICE_CKPT_DIR="${MODEL_CACHE_DIR}/checkpoints_v2"
MELO_MODELS_DIR="${MODEL_CACHE_DIR}/melo_models"
BERT_MODELS_DIR="${MODEL_CACHE_DIR}/bert_models"
NLTK_DATA_DIR="${MODEL_CACHE_DIR}/nltk_data"

mkdir -p "${OPENVOICE_CKPT_DIR}" "${MELO_MODELS_DIR}" "${BERT_MODELS_DIR}" "${NLTK_DATA_DIR}"

echo "============================================="
echo "  OpenVoice + MeloTTS 离线镜像构建脚本"
echo "============================================="
echo "镜像名:   ${IMAGE_NAME}:${IMAGE_TAG}"
echo "语言:     ${LANGUAGES}"
echo "缓存目录: ${MODEL_CACHE_DIR}"
echo ""

# ---------------------------------------------------------------------------
# 检查 hf 命令是否可用
# ---------------------------------------------------------------------------
if ! command -v hf &>/dev/null; then
    echo "错误: 未找到 hf 命令。请先安装: pip install huggingface_hub[cli]"
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. 下载 OpenVoice V2 Checkpoints
# ---------------------------------------------------------------------------
echo ""
echo ">>> [1/4] 下载 OpenVoice V2 Checkpoints ..."

# 下载 converter 模型
if [ -f "${OPENVOICE_CKPT_DIR}/converter/checkpoint.pth" ] && [ -f "${OPENVOICE_CKPT_DIR}/converter/config.json" ]; then
    echo "    converter 已存在，跳过"
else
    echo "    下载 converter ..."
    hf download myshell-ai/OpenVoiceV2 --include "converter/*" --local-dir "${OPENVOICE_CKPT_DIR}"
fi

# 下载 base_speakers SE 文件
if [ -d "${OPENVOICE_CKPT_DIR}/base_speakers/ses" ]; then
    echo "    base_speakers 已存在，跳过"
else
    echo "    下载 base_speakers ..."
    hf download myshell-ai/OpenVoiceV2 --include "base_speakers/*" --local-dir "${OPENVOICE_CKPT_DIR}"
fi

echo "    OpenVoice V2 Checkpoints 下载完成"

# ---------------------------------------------------------------------------
# 2. 下载 MeloTTS 语言模型
# ---------------------------------------------------------------------------
echo ""
echo ">>> [2/4] 下载 MeloTTS 语言模型 ..."

for lang in ${LANGUAGES}; do
    repo=$(get_melo_repo "${lang}" 2>/dev/null) || true
    if [ -z "${repo}" ]; then
        echo "    警告: 不支持的语言 ${lang}，跳过"
        continue
    fi

    lang_dir="${MELO_MODELS_DIR}/${lang}"
    if [ -f "${lang_dir}/checkpoint.pth" ] && [ -f "${lang_dir}/config.json" ]; then
        echo "    ${lang} 已存在，跳过"
        continue
    fi

    echo "    下载 ${lang} (${repo}) ..."
    mkdir -p "${lang_dir}"
    # 可选: --include "*.pth" "*.json" 仅下载部分文件
    hf download "${repo}" --local-dir "${lang_dir}"
done

echo "    MeloTTS 语言模型下载完成"

# ---------------------------------------------------------------------------
# 3. 下载 BERT 模型
# ---------------------------------------------------------------------------
echo ""
echo ">>> [3/4] 下载 BERT 模型 ..."

# 收集所需的 BERT 模型（去重）
BERT_NEEDED=""
for lang in ${LANGUAGES}; do
    bert_ids=$(get_bert_models "${lang}" 2>/dev/null) || true
    for bert_id in ${bert_ids}; do
        # 简单去重：检查是否已在列表中
        case " ${BERT_NEEDED} " in
            *" ${bert_id} "*) ;;  # 已存在，跳过
            *) BERT_NEEDED="${BERT_NEEDED} ${bert_id}" ;;
        esac
    done
done

for bert_id in ${BERT_NEEDED}; do
    # 将 model_id 中的 / 替换为 -- 作为目录名
    safe_name="${bert_id//\//__}"
    bert_dir="${BERT_MODELS_DIR}/${safe_name}"

    if [ -d "${bert_dir}" ] && [ "$(ls -A "${bert_dir}" 2>/dev/null)" ]; then
        echo "    ${bert_id} 已存在，跳过"
        continue
    fi

    echo "    下载 ${bert_id} ..."
    mkdir -p "${bert_dir}"
    hf download "${bert_id}" --local-dir "${bert_dir}"
done

echo "    BERT 模型下载完成"

# ---------------------------------------------------------------------------
# 4. 下载 NLTK 数据包
# ---------------------------------------------------------------------------
echo ""
echo ">>> [4/5] 下载 NLTK 数据包 ..."

# 检查 Python 是否可用
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "    警告: 未找到 Python，跳过 NLTK 数据下载"
    echo "    将在 Docker 构建时下载"
else
    PYTHON_CMD="python3"
    if ! command -v python3 &>/dev/null; then
        PYTHON_CMD="python"
    fi
    
    # 检查是否已有数据
    if [ -d "${NLTK_DATA_DIR}/taggers" ] && [ -d "${NLTK_DATA_DIR}/corpora" ]; then
        echo "    NLTK 数据已存在，跳过"
    else
        echo "    下载 NLTK 数据包到 ${NLTK_DATA_DIR} ..."
        
        # 尝试导入 nltk，如果失败则安装
        if ! ${PYTHON_CMD} -c "import nltk" 2>/dev/null; then
            echo "    安装 nltk ..."
            ${PYTHON_CMD} -m pip install -q nltk
        fi
        
        # 下载所需的 NLTK 数据包
        for pkg in ${NLTK_PACKAGES}; do
            echo "    下载 ${pkg} ..."
            ${PYTHON_CMD} -c "
import nltk
import os
os.makedirs('${NLTK_DATA_DIR}', exist_ok=True)
try:
    nltk.download('${pkg}', download_dir='${NLTK_DATA_DIR}', quiet=True)
    print('    ✓ ${pkg} 完成')
except Exception as e:
    print(f'    ✗ ${pkg} 失败: {e}')
" || echo "    ✗ ${pkg} 下载失败"
        done
    fi
fi

echo "    NLTK 数据包下载完成"

# ---------------------------------------------------------------------------
# 5. Docker 构建
# ---------------------------------------------------------------------------
echo ""
echo ">>> [5/5] 构建 Docker 镜像 ..."

# 将语言列表传入构建参数
docker build \
    --build-arg LANGUAGES="${LANGUAGES}" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -f Dockerfile \
    .

echo ""
echo "============================================="
echo "  构建完成: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "============================================="
echo ""
echo "运行示例:"
echo "  docker run --gpus all -p 9883:9883 ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "离线测试（断网运行）:"
echo "  docker run --gpus all --network=none -p 9883:9883 ${IMAGE_NAME}:${IMAGE_TAG}"
