# unitree-g1-xr_teleope
unitree g1でquest3を用いて遠隔操縦をするための環境構築

## 1. unitree_sim_env(シミュレーション環境)の作成
参考ソース：
unitree_sim_isaaclab 公式 Isaac Sim 5.1.0 環境構築手順https://github.com/unitreerobotics/unitree_sim_isaaclab/blob/main/doc/isaacsim5.1_install.md
unitree_sim_isaaclab 公式リポジトリ
https://github.com/unitreerobotics/unitree_sim_isaaclab/tree/main

Unitree G1 + Isaac Sim / IsaacLab 用のconda環境として、unitree_sim_envを作成する。
```code
conda create -n unitree_sim_env python=3.11 -y
conda activate unitree_sim_env
```
## 2. PyTorch / torchvision のインストール
PyTorchは、CUDA 12.8用のwheelを使用する。
```code
pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
```
補足：
nvidia-smi上のCUDA Version表示は13.0だが、PyTorch側はtorch==2.7.0+cu128としてCUDA 12.8用wheelを使用している。

## 3. Isaac Sim 5.1.0 のインストール
Isaac Simは、pip版のisaacsim[all,extscache]==5.1.0を使用する。
```code
python -m pip install --upgrade pip
pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
```

初回importまたは初回起動時にOmniverse KitのEULA同意が必要になる場合がある。
その場合のみ、以下を一時的に指定して実行する。
```code
export OMNI_KIT_ACCEPT_EULA=yes
```

## 4. unitree_sim_isaaclab の取得
ホームディレクトリ直下にunitree_sim_isaaclabを配置する。
```code
cd ~
git clone https://github.com/unitreerobotics/unitree_sim_isaaclab.git
cd unitree_sim_isaaclab
git submodule update --init --depth 1
```

補足：
公式手順ではSSH形式のcloneが示されているが、SSH鍵設定を前提にしないため、今回はHTTPS形式でcloneした。

補足：
OMNI_KIT_ACCEPT_EULA=yesは初回実行時の同意用として一時的に使用した。

## 5.起動手順
### ローカルPC
```code
source ~/miniconda3/etc/profile.d/conda.sh
```
```code
sudo ip addr flush dev enp45s0
sudo ip addr add 192.168.123.200/24 dev enp45s0
sudo ip link set enp45s0 up
```
```code
python teleop_hand_and_arm.py \
 --input-mode=controller \
 --arm=G1_23 \
 --sim \
 --img-server-ip=192.168.123.164 \
 --display-mode=immersive \
 --network-interface enp45s0
```


