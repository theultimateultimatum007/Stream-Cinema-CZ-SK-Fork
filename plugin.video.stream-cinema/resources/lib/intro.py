from resources.lib.api.kraska import Kraska
from resources.lib.common.logger import info, debug
from resources.lib.gui.dialog import dyesno, dinput, dok
from resources.lib.kodiutils import get_setting, set_setting, open_settings
from resources.lib.language import Strings


def intro(step=None, credentials_only=False):
    info('Step: {}'.format(step))
    auto_close = 60

    if step is None and get_setting('kraska.user') != '':
        info('Uz nieje treba intro....')
        return
    elif step is None:
        step = 1

    if step == 1:
        start = dyesno(Strings.txt(Strings.INTRO_STEP1_H1), Strings.txt(Strings.INTRO_STEP1_L1), autoclose=auto_close)
        info('RET: [{}] [{}]'.format(start, 'Ano' if start else 'Nie'))
        return intro(step + 1, credentials_only) if start == 1 else 0

    if step == 2:
        user = dinput(Strings.txt(Strings.INTRO_STEP2_H1), get_setting('kraska.user'))
        if user == '':
            # Zruseny dialog / prazdne meno - nic neprepisujeme, povodne
            # nastavenia ostavaju nedotknute
            debug('intro: prazdne meno, koncim bez zmeny nastaveni')
            return 0
        set_setting('kraska.user', user)
        if user != get_setting('kraska.user'):
            # Zapis sa neprejavil - skusime znova (rovnaky vzor ako pri hesle).
            # Nikdy nemazeme settings.xml - prisli by sme o vsetky nastavenia.
            debug('intro: skusam znova zapisat uzivatela...')
            set_setting('kraska.user', user)
        return intro(step + 1, credentials_only)

    if step == 3:
        password = dinput(Strings.txt(Strings.INTRO_STEP3_H1), '')
        if password == '':
            debug('intro: prazdne heslo, koncim bez zmeny nastaveni')
            return 0
        set_setting('kraska.pass', password)
        if password != get_setting('kraska.pass'):
            debug('intro: skusam znova zapisat heslo...')
            set_setting('kraska.pass', password)
        kr = Kraska(p=password)
        data = kr.user_info()
        if data is False:
            return intro(step + 1, credentials_only)
        # Nove udaje su overene - zahodime singleton, aby si zvysok pluginu
        # pri dalsom pristupe nacital cerstve credentials zo settings
        # (stara instancia drzi username/password z casu svojej konstrukcie)
        Kraska.instance = None
        return intro(step + 2, credentials_only)

    if step == 4:
        dok(Strings.txt(Strings.INTRO_STEP4_H1), Strings.txt(Strings.INTRO_STEP4_L1))
        return intro(step - 2, credentials_only)

    if step == 5 and credentials_only is False:
        res = dyesno(Strings.txt(Strings.INTRO_STEP5_H1), Strings.txt(Strings.INTRO_STEP5_L1))
        if res:
            open_settings('1.0')
