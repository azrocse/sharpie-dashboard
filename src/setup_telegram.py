"""Configuración local interactiva. El token nunca se escribe en Git ni en HTML."""
from getpass import getpass
from pathlib import Path
from telegram_alerts import Bot, TelegramError
from storage import atomic_write_json


def main():
    print('Configuración privada de Telegram para SharpIE.')
    token=getpass('Token de BotFather (oculto): ').strip()
    try:
        identity=Bot(token).call('getMe',{})
    except TelegramError:
        raise SystemExit('No se pudo validar el bot. No se guardó la configuración.') from None
    audience=input('¿Suscripciones públicas para cualquier usuario? [s/N]: ').strip().lower()=='s'
    ids=[] if audience else [x.strip() for x in input('IDs numéricos de chats personales permitidos, separados por coma: ').split(',') if x.strip()]
    if not audience and (not ids or any(not x.isdigit() for x in ids)):
        raise SystemExit('Falta una lista válida de chats permitidos.')
    path=Path(__file__).resolve().parent.parent/'.runtime'/'telegram.json'
    atomic_write_json(path,{'enabled':True,'token':token,'username':identity['username'],
                            'publicSubscriptions':audience,'allowedChatIds':ids})
    print(f"Bot @{identity['username']} configurado. El próximo procesamiento habilitará los enlaces.")


if __name__=='__main__':
    main()
