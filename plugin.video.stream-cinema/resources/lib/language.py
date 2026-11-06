from __future__ import print_function, unicode_literals

import re
import xbmc

from resources.lib.constants import ADDON, PY2


class Strings:
    SETUP_VIDEO_CACHE_MSG1 = 30120
    SETUP_VIDEO_CACHE_MSG2 = 30121
    SETUP_VIDEO_CACHE_MSG3 = 30122
    SETUP_VIDEO_CACHE_MSG4 = 30123

    INTRO_STEP1_H1 = 30100
    INTRO_STEP1_L1 = 30101

    INTRO_STEP2_H1 = 30012

    INTRO_STEP3_H1 = 30013

    INTRO_STEP4_H1 = 30102
    INTRO_STEP4_L1 = 30103

    INTRO_STEP5_H1 = 30104
    INTRO_STEP5_L1 = 30105

    KRASKA_NOTIFY_LOW_DAYS_LEFT = 30106
    KRASKA_NOTIFY_CREDENTIAL_H1 = 30107
    KRASKA_NOTIFY_CREDENTIAL_L1 = 30108
    KRASKA_NOTIFY_NO_SUBSCRIPTION = 30131

    SYSTEM_H1 = 30109
    SYSTEM_DEBUG_ENABLED = 30110
    SYSTEM_DEBUG_DISABLED = 30111
    SYSTEM_NOT_INSTALLED_FROM_REPOSITORY = 30127

    RESOLVE_ERROR_H1 = 30112
    RESOLVE_ERROR_L1 = 30113

    HELPER_ERROR_H1 = 30333
    HELPER_START_FAILED_L1 = 30334

    SYSTEM_API_ERROR_L1 = 30114

    CONTEXT_PIN_UNPIN = 30115
    CONTEXT_SELECT_STREAM = 30116
    CONTEXT_DOWNLOAD = 30119
    CONTEXT_ADD_TO_ANDROID_TV = 30124
    CONTEXT_PIN_TO_HP = 30125
    CONTEXT_REMOVE = 30126
    CONTEXT_ADD_TO_LIBRARY = 30128
    CONTEXT_ADD_TO_LIBRARY_WITH_SUB = 30129
    CONTEXT_REMOVE_FROM_SUB = 30130
    CONTEXT_DEL_PREF_LANG = 30132
    CONTEXT_ADD_PREF_LANG = 30133

    EMPTY_HISTORY_H1 = 30117
    EMPTY_HISTORY_L1 = 30118

    CONTEXT_BUG_REPORT = 30400
    BUG_CAT_STREAM_BROKEN = 30401
    BUG_CAT_STREAM_MISMATCH = 30402
    BUG_CAT_AV_SYNC = 30403
    BUG_CAT_GENERAL = 30404
    BUG_REPORT_STEP1 = 30405
    BUG_REPORT_STEP2 = 30406
    BUG_REPORT_DESCRIBE = 30407
    BUG_REPORT_DESCRIBE_REQUIRED = 30408
    BUG_REPORT_ATTACH_USER = 30409
    BUG_REPORT_ATTACH_LOG = 30410
    BUG_REPORT_PREVIEW_H1 = 30411
    BUG_REPORT_BTN_SEND = 30412
    BUG_REPORT_BTN_BACK = 30413
    BUG_REPORT_BTN_CANCEL = 30414
    BUG_REPORT_OFFER = 30415
    BUG_REPORT_SENT = 30416
    BUG_REPORT_QUEUED = 30417
    BUG_REPORT_CONFIRM_SEND = 30418

    DOWNLOAD_QUEUE = 30430
    DOWNLOAD_QUEUE_EMPTY = 30431
    DOWNLOAD_QUEUED = 30432
    DOWNLOAD_QUEUE_FULL = 30433
    DOWNLOAD_QUEUE_CLEAR_FINISHED = 30434
    DOWNLOAD_QUEUE_CLEAR_ALL = 30435
    DOWNLOAD_QUEUE_REMOVE = 30436
    DOWNLOAD_STATUS_PENDING = 30437
    DOWNLOAD_STATUS_DOWNLOADING = 30438
    DOWNLOAD_STATUS_DONE = 30439
    DOWNLOAD_STATUS_ERROR = 30440
    DOWNLOAD_FINISHED = 30441
    DOWNLOAD_FAILED = 30442
    DOWNLOAD_ALREADY_QUEUED = 30443
    DOWNLOAD_NO_PATH = 30444

    @staticmethod
    def interpolate(id):
        return '${}'.format(id)

    @staticmethod
    def txt(id):
        return get_localized_string(id)


def get_localized_string(string_id):
    if PY2:
        return ADDON.getLocalizedString(string_id).encode('utf-8')
    return ADDON.getLocalizedString(string_id)


def get_language_code():
    return xbmc.getLanguage(xbmc.ISO_639_1)


def translate(text):
    if PY2:
        text = text.encode('utf-8')
    if text is not None and '$' in text:
        translation_strings = list(
            re.finditer(r'\$([0-9]+)', text, re.IGNORECASE | re.DOTALL)
        )
        for i in translation_strings:
            try:
                translated = get_localized_string(int(i.group(1)))
                text = text.replace('${0}'.format(i.group(1)), translated)
            except Exception as e:
                pass

    return text
