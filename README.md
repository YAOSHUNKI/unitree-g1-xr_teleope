# unitree-g1-xr_teleope
unitree g1でquest3を用いて遠隔操縦をするための環境構築

## 1. unitree_sim_env(シミュレーション環境)の作成
参考ソース：
unitree_sim_isaaclab 公式 Isaac Sim 5.1.0 環境構築手順https://github.com/unitreerobotics/unitree_sim_isaaclab/blob/main/doc/isaacsim5.1_install.md
unitree_sim_isaaclab 公式リポジトリ
https://github.com/unitreerobotics/unitree_sim_isaaclab/tree/main

Unitree G1 + Isaac Sim / IsaacLab 用のconda環境として、unitree_sim_envを作成する。
'''
conda create -n unitree_sim_env python=3.11 -y
conda activate unitree_sim_env
'''

## 5.起動手順
### ローカルPC
python teleop_hand_and_arm.py \
 --input-mode=controller \
 --arm=G1_23 \
 --sim \
 --img-server-ip=192.168.123.164 \
 --display-mode=immersive \
 --network-interface enp45s0


