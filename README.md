# unitree-g1-xr_teleoperate
 
Unitree G1 で Meta Quest 3 を用いて遠隔操縦を行うための環境構築手順。
 
## 参考ソース
 
- [unitree_sim_isaaclab 公式 Isaac Sim 5.1.0 環境構築手順](https://github.com/unitreerobotics/unitree_sim_isaaclab/blob/main/doc/isaacsim5.1_install.md)
- [unitree_sim_isaaclab 公式リポジトリ](https://github.com/unitreerobotics/unitree_sim_isaaclab/tree/main)
- [xr_teleoperate 公式 README](https://github.com/unitreerobotics/xr_teleoperate/blob/main/README.md)
---
 
# 環境構築
 
## 1. unitree_sim_env(シミュレーション環境)の作成
 
Unitree G1 + Isaac Sim / IsaacLab 用の conda 環境として `unitree_sim_env` を作成する。
 
```bash
conda create -n unitree_sim_env python=3.11 -y
conda activate unitree_sim_env
```
 
## 2. PyTorch / torchvision のインストール
 
PyTorch は CUDA 12.8 用の wheel を使用する。
 
```bash
pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
```
 
> **補足:** `nvidia-smi` 上の CUDA Version 表示は 13.0 だが、PyTorch 側は `torch==2.7.0+cu128` として CUDA 12.8 用 wheel を使用している。
 
## 3. Isaac Sim 5.1.0 のインストール
 
pip 版の `isaacsim[all,extscache]==5.1.0` を使用する。
 
```bash
python -m pip install --upgrade pip
pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
```
 
初回 import または初回起動時に Omniverse Kit の EULA 同意が必要になる場合がある。その場合のみ、以下を一時的に指定して実行する。
 
```bash
export OMNI_KIT_ACCEPT_EULA=yes
```
 
> **補足:** `OMNI_KIT_ACCEPT_EULA=yes` は初回実行時の同意用として一時的に使用した。
 
## 4. unitree_sim_isaaclab の取得
 
ホームディレクトリ直下に `unitree_sim_isaaclab` を配置する。
 
```bash
cd ~
git clone https://github.com/unitreerobotics/unitree_sim_isaaclab.git
cd unitree_sim_isaaclab
git submodule update --init --depth 1
```
 
> **補足:** 公式手順では SSH 形式の clone が示されているが、SSH 鍵設定を前提にしないため、今回は HTTPS 形式で clone した。
 
## 5. teleimager 設定ファイルの修正
 
submodule 初期化後、公式手順に従って `teleimager/cam_config_server.yaml` を修正する。
 
```bash
cd ~/unitree_sim_isaaclab
sed -i 's/image_shape: \[.*\]/image_shape: [480, 640]/' teleimager/cam_config_server.yaml
sed -i 's/type: .*/type: isaacsim/' teleimager/cam_config_server.yaml
```
 
## 6. IsaacLab のインストール
 
IsaacLab は `~/unitree_sim_isaaclab/IsaacLab` に配置する。
 
```bash
cd ~/unitree_sim_isaaclab
git clone https://github.com/isaac-sim/IsaacLab.git
sudo apt install cmake build-essential
cd IsaacLab
export OMNI_KIT_ACCEPT_EULA=yes
./isaaclab.sh --install
```
 
## 7. Unitree SDK と CycloneDDS の準備
 
Unitree SDK を使用するため `unitree_sdk2_python` を取得する。SDK インストール時に CycloneDDS が必要になるため、CycloneDDS をソースからビルドする。
 
```bash
cd ~/unitree_sim_isaaclab
git clone https://github.com/unitreerobotics/unitree_sdk2_python
```
 
```bash
cd ~
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x
cd cyclonedds
mkdir build install
cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install
```
 
## 8. unitree_sdk2_python のインストール
 
CycloneDDS をビルドした後、環境変数 `CYCLONEDDS_HOME` と `CMAKE_PREFIX_PATH` を指定して `unitree_sdk2_python` をインストールする。
 
```bash
cd ~/unitree_sim_isaaclab/unitree_sdk2_python
export CYCLONEDDS_HOME="$HOME/cyclonedds/install"
export CMAKE_PREFIX_PATH="$CYCLONEDDS_HOME:${CMAKE_PREFIX_PATH}"
pip install -e .
pip install numpy==1.26.4
```
 
> **補足:** `unitree_sdk2_python` のインストール後、NumPy が 2 系へ上がったため、`numpy==1.26.4` へ戻した。
 
> **補足:** `pip install -e .` および `pip install numpy==1.26.4` の後に、pip の dependency resolver に関する警告が表示された。内容としては、Isaac Sim、IsaacLab、dex-retargeting、rl-games、opencv-python などの要求バージョンと一部のパッケージバージョンが一致していないというものであった。
>
> ただし、今回の段階では、追加で `click`、`psutil`、`typing_extensions`、`torchaudio` などを個別に固定することはしなかった。理由は、今後の `requirements.txt` や実機接続関連の依存関係と競合する可能性があるためである。現時点では、NumPy を 2 系から 1.26.4 へ戻すことを優先した。
 
## 9. requirements.txt のインストール
 
```bash
cd ~/unitree_sim_isaaclab
pip install -r requirements.txt
```
 
> **補足:** この段階でも pip の依存関係警告が出る可能性があるが、実際にインストール処理が途中で停止していなければ、いったん次の手順へ進む方針とした。
 
## 10. assets の取得
 
```bash
conda activate unitree_sim_env
cd ~/unitree_sim_isaaclab
sudo apt update
sudo apt install -y git-lfs
. fetch_assets.sh
```
 
## 11. teleimager のインストール
 
```bash
cd ~/unitree_sim_isaaclab/teleimager
pip install -e . --no-deps
```
 
## 12. tv 環境の作成
 
Meta Quest 3 接続および遠隔操作側の環境として `tv` 環境を作成する。
 
```bash
conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge -y
conda activate tv
```
 
> **補足:** `unitree_sim_env` は Isaac Sim / IsaacLab 用の環境であり、Isaac Sim 5.1.0 に合わせて Python 3.11 を使用した。一方、`tv` 環境は xr_teleoperate / televuer / teleimager / Unitree SDK 用の環境であり、`unitree_sim_env` と Python バージョンを合わせる必要はない。そのため、`tv` 環境は公式 README に合わせて Python 3.10 とした。
 
## 13. xr_teleoperate の取得
 
```bash
cd ~
git clone https://github.com/unitreerobotics/xr_teleoperate.git
cd xr_teleoperate
git submodule update --init --depth 1
```
 
## 14. teleimager と televuer のインストール
 
xr_teleoperate 側の submodule として含まれる `teleimager` と `televuer` をインストールする。
 
```bash
cd ~/xr_teleoperate/teleop/teleimager
pip install -e . --no-deps
```
 
```bash
cd ~/xr_teleoperate/teleop/televuer
pip install -e .
```
 
> **補足:** `teleimager` は公式 README に合わせて `--no-deps` 付きでインストールした。そのため、以下のような依存関係警告が表示された。
>
> ```
> teleimager 1.5.0 requires pyyaml, which is not installed.
> teleimager 1.5.0 requires pyzmq, which is not installed.
> ```
>
> これは `--no-deps` で依存関係を同時に入れなかったために出た警告である。次の手順で `pyyaml` と `pyzmq` をインストールするため、この段階では問題ない。
 
## 15. pyyaml / pyzmq / params_proto のインストール
 
teleimager の依存関係として必要になる `pyyaml` と `pyzmq` をインストールする。また、`params_proto` のバージョンによる不具合があったため `params_proto==2.13.2` に固定した。
 
```bash
pip install pyyaml pyzmq
pip install params_proto==2.13.2
```
 
## 16. SSL 証明書の作成と 8012 番ポートの許可
 
Meta Quest 3 から WebXR 接続するため、自己署名証明書を作成し `~/.config/xr_teleoperate/` に配置する。また、8012 番ポートを許可する。
 
```bash
cd ~/xr_teleoperate/teleop/televuer
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem
sudo ufw allow 8012
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```
 
> **補足:** `openssl` 実行時に入力を求められるが、すべて Enter でスキップした。
 
## 17. tv 環境側の unitree_sdk2_python のインストール
 
`tv` 環境側でも Unitree SDK をインストールする。これは G1 や Dex3 との DDS 通信に必要になる。
 
```bash
cd ~
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
export CYCLONEDDS_HOME="$HOME/cyclonedds/install"
export CMAKE_PREFIX_PATH="$CYCLONEDDS_HOME:${CMAKE_PREFIX_PATH}"
pip install -e .
```
 
## 18. 不足依存の追加
 
起動時に不足している Python モジュールがいくつか見つかったため、必要なものを追加インストールする。
 
```bash
pip install meshcat
pip install matplotlib
pip install rerun-sdk==0.20.1
pip install sshkeyboard
```
 
> **補足:** rerun は `rerun-sdk` で提供される。最新版の `rerun-sdk` を入れると NumPy 2 系へ寄る可能性があったため、`rerun-sdk==0.20.1` に固定した。
 
> **補足:** 公式 README にはこれらの追加依存が明示されていないが、`teleop_hand_and_arm.py` 実行時に不足が判明したため、必要な推定手順として追加インストールした。
 
## 19. dex-retargeting のインストール
 
Dex3 + hand mode では、手指の retargeting 処理に `dex-retargeting` が必要になる。そのため、xr_teleoperate 内の `dex-retargeting` を Python パッケージとしてインストールする。
 
```bash
cd ~/xr_teleoperate/teleop/robot_control/dex-retargeting
pip install -e .
```
 
> **補足:** Dex3 + hand mode を使用する場合、`teleop/robot_control/hand_retargeting.py` 内で `dex_retargeting` を使用するため、この手順が必要になる。
 
---
 
# 起動手順
 
## 有線 Ethernet による接続
 
### ローカル PC
 
```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
```
 
```bash
sudo ip addr flush dev enp45s0
sudo ip addr add 192.168.123.200/24 dev enp45s0
sudo ip link set enp45s0 up
```
 
```bash
python teleop_hand_and_arm.py \
    --input-mode=controller \
    --arm=G1_23 \
    --img-server-ip=192.168.123.164 \
    --display-mode=immersive \
    --network-interface enp45s0
```
 
### G1 側 PC
 
```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate teleimager
```
 
```bash
cd ~/teleimager
teleimager-server --rs
```
 
---
 
## 無線 ssh による接続
 
### 前提
 
- 必ず G1、ローカル PC（制御ノート PC）、Quest を同じ Wi-Fi に接続する。
- G1 を立たせるときに **L2 + 十字キー上**(Locked Standing)の後、**R1 + X** で Regular Mode に切り替える。
### ローカル PC から G1 内の PC に ssh 接続
 
内部 PC の `wlan0` の IP アドレスを確認する。
 
例:
```bash
ssh unitree@10.10.129.69
```
 
実際のコマンド:
```bash
ssh unitree@<調べたwlan0のIPアドレス>
```
 
> `ros: foxy(1) noetic(2) ?` と聞かれるので `Ctrl+C` でスキップする。
 
2 つのターミナルで起動する。
 
### ターミナル 1(画像サーバ)
 
```bash
tmux new -s img
```
 
> `ros: foxy(1) noetic(2) ?` と聞かれるので `Ctrl+C` でスキップする。
 
```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
```
 
```bash
cd ~/teleimager
python -m teleimager.image_server --rs
```
 
### ターミナル 2(遠隔操作)
 
```bash
tmux new -s teleop
```
 
> `ros: foxy(1) noetic(2) ?` と聞かれるので `Ctrl+C` でスキップする。
 
```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
```
 
ここの IP は `wlan0` の IP アドレス。
 
例:
```bash
cd ~/xr_teleoperate/teleop
python teleop_hand_and_arm.py \
    --input-mode=controller \
    --motion \
    --arm G1_23 \
    --network-interface eth0 \
    --img-server-ip 10.10.129.69
```
 
実際のコマンド (上記で調べた `wlan0` の IP アドレスと同じ):
```bash
cd ~/xr_teleoperate/teleop
python teleop_hand_and_arm.py \
    --input-mode=controller \
    --motion \
    --arm G1_23 \
    --network-interface eth0 \
    --img-server-ip <調べたwlan0のIPアドレス>
```
 
起動を確認した後に `r` を入力すると制御準備完了。
 
### Quest でアクセスする URL
 
例:
```
https://10.10.129.69:8012/?ws=wss://10.10.129.69:8012
```
 
実際の URL (上記で調べた `wlan0` の IP アドレスと同じ):
```
https://<調べたwlan0のIPアドレス>:8012/?ws=wss://<調べたwlan0のIPアドレス>:8012
```
 
- Web の安全性の警告が出るが無視して開く。
- G1 の RealSense の映像を取得する場合は **Realsense visual**。
- VR を透過させる場合は **pass through**。
 