# docling-serve pinned by digest + Tesseract `por` model (the upstream image ships only eng/osd).
# Build: docker build -t arquivio-docling:v1.35.0-pt1 infra/docling
# Digest below = quay.io/docling-project/docling-serve-cpu:v1.35.0 (multi-arch index would also work; this one was validated).
FROM quay.io/docling-project/docling-serve-cpu:v1.35.0@sha256:79e5fcd19ab227ed36323fa5fa31820d14d53efc4f073417ba37be7931c7af0a

# tessdata_best 4.1.0 (LSTM, 8.2 MB). Compared with tessdata_fast in docs/operacao/validacao-2026-09-30.md.
ARG TESSDATA_VARIANT=best
ARG TESSDATA_SHA256=711de9dbb8052067bd42f16b9119967f30bada80d57e2ef24f65d09f531adb04
ADD --checksum=sha256:${TESSDATA_SHA256} --chmod=0644 \
    https://raw.githubusercontent.com/tesseract-ocr/tessdata_${TESSDATA_VARIANT}/4.1.0/por.traineddata \
    /usr/share/tesseract/tessdata/por.traineddata
