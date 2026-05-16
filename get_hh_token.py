"""
Одноразовый скрипт: обмен authorization code на access_token.
Запуск: python get_hh_token.py --client_id ID --client_secret SECRET --code CODE
"""

import argparse

import httpx

TOKEN_URL = "https://hh.ru/oauth/token"


def exchange_code(client_id: str, client_secret: str, code: str) -> None:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        },
        headers={"HH-User-Agent": "job_analyzer_mvp/1.0"},
        timeout=15.0,
    )
    if resp.status_code != 200:
        print(f"Ошибка {resp.status_code}: {resp.text}")
        return

    data = resp.json()
    token = data.get("access_token", "")
    if token:
        print(f"Access token:\n{token}")
        print("\nСохраните в файл секрета:")
        print(f"  echo '{token}' > ~/job-analyzer-secrets/hh_token.txt")
    else:
        print(f"Ответ: {data}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--client_id", required=True)
    parser.add_argument("--client_secret", required=True)
    parser.add_argument("--code", required=True)
    args = parser.parse_args()
    exchange_code(args.client_id, args.client_secret, args.code)
