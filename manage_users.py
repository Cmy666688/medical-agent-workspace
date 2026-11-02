"""Trusted machine-owner bootstrap; no web endpoint or password output."""
import argparse
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='为本服务的已注册用户授予管理员权限')
    parser.add_argument('username')
    parser.add_argument('--runtime-profile',choices=['local','public'],default='local')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent/'runtime'
    os.environ['MEDICAL_RUNTIME_DIR']=str(root/'public' if args.runtime_profile=='public' else root)
    from agents.user_management import bootstrap_admin
    bootstrap_admin(args.username)
    print(f'Administrator configured: {args.runtime_profile} / {args.username}')


if __name__=='__main__': main()
