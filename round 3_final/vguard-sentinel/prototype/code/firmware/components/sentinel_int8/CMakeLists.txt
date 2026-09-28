# firmware/components/sentinel_int8 -- hand-written C99 int8 CNN inference, the
# firmware-owned counterpart to model/int8_infer.py (see sentinel_int8.c doc comment).
#
# Weights come from model/artifacts_sim/sentinel_model_int8.h, included by path (not
# copied) -- CONTRACTS.md: model artifacts are owned by module E (model/), firmware
# only reads the exported header. Swap INCLUDE_DIRS to point at model/artifacts/ (the
# non-"_sim" real-campaign export) when that exists.
idf_component_register(
    SRCS "sentinel_int8.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "../../../model/artifacts_sim"
    REQUIRES ""
)
