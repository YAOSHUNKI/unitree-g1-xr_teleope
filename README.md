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
補足：
OMNI_KIT_ACCEPT_EULA=yesは初回実行時の同意用として一時的に使用した。

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

## 5. teleimager 設定ファイルの修正
unitree_sim_isaaclab のsubmodule初期化後、公式手順に従って teleimager/cam_config_server.yaml を修正する。

```code
cd ~/unitree_sim_isaaclab
sed -i 's/image_shape: \[.*\]/image_shape: [480, 640]/' teleimager/cam_config_server.yaml
sed -i 's/type: .*/type: isaacsim/' teleimager/cam_config_server.yaml
```

## 6.IsaacLabのインストール
IsaacLabは、~/unitree_sim_isaaclab/IsaacLab に配置する。
```code
cd ~/unitree_sim_isaaclab
```
```code
git clone https://github.com/isaac-sim/IsaacLab.git
```
```code
sudo apt install cmake build-essential
```
```code
cd IsaacLab
export OMNI_KIT_ACCEPT_EULA=yes
./isaaclab.sh --install
```

## 7.Unitree SDK と CycloneDDS の準備
Unitree SDKを使用するため、unitree_sdk2_pythonを取得する。 また、SDKインストール時にCycloneDDSが必要になるため、CycloneDDSをソースからビルドする。
```code
cd ~/unitree_sim_isaaclab
git clone https://github.com/unitreerobotics/unitree_sdk2_python
```
```code
cd ~
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x cd cyclonedds
mkdir build install
cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install
```

## 8.unitree_sdk2_python のインストール 
CycloneDDSをビルドした後、環境変数CYCLONEDDS_HOMEとCMAKE_PREFIX_PATHを指定して、unitree_sdk2_pythonをインストールする。
```code
cd ~/unitree_sim_isaaclab/unitree_sdk2_python
```
```code
export CYCLONEDDS_HOME="$HOME/cyclonedds/install"
export CMAKE_PREFIX_PATH="$CYCLONEDDS_HOME:${CMAKE_PREFIX_PATH}"
```
```code
pip install -e .
```
```code
pip install numpy==1.26.4
```
補足: unitree_sdk2_pythonのインストール後、NumPyが2系へ上がったため、numpy==1.26.4へ戻した。
補足:
pip install -e .およびpip install numpy==1.26.4の後に、pipのdependency resolverに関する警告が表示された。
内容としては、Isaac Sim、IsaacLab、dex-retargeting、rl-games、opencv-pythonなどの要求バージョンと一部のパッケージバージョンが一致していないというものであった。
ただし、今回の段階では、追加でclick、psutil、typing_extensions、torchaudioなどを個別に固定することはしなかった。 理由は、今後のrequirements.txtや実機接続関連の依存関係と競合する可能性があるためである。
現時点では、NumPyを2系から1.26.4へ戻すことを優先した。

## 9.requirements.txt のインストール
unitree_sim_isaaclabで必要なPythonパッケージをインストールする。
```code
cd ~/unitree_sim_isaaclab
```
```code
pip install -r requirements.txt
```
補足: この段階でもpipの依存関係警告が出る可能性があるが、実際にインストール処理が途中で 停止していなければ、いったん次の手順へ進む方針とした。

## 10.assetsの取得
unitree_sim_isaaclabの実行に必要なロボットモデルや環境モデルなどのassetsを取得する。
```code
conda activate unitree_sim_env
cd ~/unitree_sim_isaaclab
```
```code
sudo apt update
sudo apt install -y git-lfs
```
```code
. fetch_assets.sh
```

## 11.teleimagerのインストール
```code
cd ~/unitree_sim_isaaclab/teleimager
```
```code
pip install -e . --no-deps
```

## 12.tv環境の作成
参考ソース:
xr_teleoperate 公式README
https://github.com/unitreerobotics/xr_teleoperate/blob/main/README.md
Meta Quest 3接続および遠隔操作側の環境として、tv環境を作成する
```code
conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge -y
conda activate tv
```
補足:
unitree_sim_envはIsaac Sim / IsaacLab用の環境であり、Isaac Sim 5.1.0に合わせてPython3.11を使用した。
一方、tv環境はxr_teleoperate / televuer / teleimager / Unitree SDK用の環境であり、unitre e_sim_envとPythonバージョンを合わせる必要はない。 そのため、tv環境は公式READMEに合わせてPython 3.10とした。

## 13.xr_teleoperateの取得
xr_teleoperateをホームディレクトリ直下に取得し、submoduleを初期化する。
```code
cd ~
git clone https://github.com/unitreerobotics/xr_teleoperate.git
cd xr_teleoperate
git submodule update --init --depth 1
```

## 14.teleimagerとtelevuerのインストール
xr_teleoperate側のsubmoduleとして含まれるteleimagerとtelevuerをインストールする。
```code
cd ~/xr_teleoperate/teleop/teleimager
pip install -e . --no-deps
```
```code
cd ~/xr_teleoperate/teleop/televuer
pip install -e .
```
補足: teleimagerは公式READMEに合わせて--no-deps付きでインストールした。 
そのため、以下のような依存関係警告が表示された。
```code
teleimager 1.5.0 requires pyyaml, which is not installed.
teleimager 1.5.0 requires pyzmq, which is not installed.
```
これは--no-depsで依存関係を同時に入れなかったために出た警告である。 
次の手順でpyyamlとpyzmqをインストールするため、この段階では問題ない。

## 15.pyyaml/pysmq/params_protoのインストール
teleimagerの依存関係として必要になるpyyamlとpyzmqをインストールした。
また、params_protoのバージョンによる不具合があったため、params_proto==2.13.2に固定した。
```code
pip install pyyaml pyzmq
pip install params_proto==2.13.2
```

## 16.SSL証明書の作成と8012番ポートの許可
Meta Quest 3からWebXR接続するため、自己署名証明書を作成し、~/.config/xr_teleoper ate/に配置する。
また、8012番ポートを許可する。
```code
cd ~/xr_teleoperate/teleop/televuer
```
```code
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem
```
```code
sudo ufw allow 8012
```
```code
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```
補足: openssl実行時に入力を求められるが、すべてEnterでスキップした。

## 17.tv環境側のunitree_sdk2_pythonのインストール
tv環境側でも、Unitree SDKをインストールする。これはG1やDex3とのDDS通信に必要になる。
```code
cd ~
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
```
```code
cd unitree_sdk2_python
```
```code
export CYCLONEDDS_HOME="$HOME/cyclonedds/install"
export CMAKE_PREFIX_PATH="$CYCLONEDDS_HOME:${CMAKE_PREFIX_PATH}"
```
```code
pip install -e .
```

## 18.不足依存の追加
起動時に不足しているPythonモジュールがいくつか見つかったため、必要なものを追加インストールした。
```code
pip install meshcat
pip install matplotlib
pip install rerun-sdk==0.20.1
pip install sshkeyboard
```
補足: 
rerunはrerun-sdkで提供される。
最新版のrerun-sdkを入れるとNumPy 2系へ寄る可能性があったため、rerun-sdk==0.20.1 に固定した。

補足: 
公式READMEにはこれらの追加依存が明示されていないが、teleop_hand_and_arm.py実行時に不足が判明したため、必要な推定手順として追加インストールした。

## 19.dex-retargetingのインストール
Dex3 + hand modeでは、手指のretargeting処理にdex-retargetingが必要になる。 
そのため、xr_teleoperate内のdex-retargetingをPythonパッケージとしてインストールした。
```code
cd ~/xr_teleoperate/teleop/robot_control/dex-retargeting
```
```code
pip install -e .
```
補足:
Dex3 + hand modeを使用する場合、teleop/robot_control/hand_retargeting.py内でdex_r etargetingを使用するため、この手順が必要になる。

# 起動手順
## 有線 Ethernetによる接続
### ローカルPC
```code
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
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
 --img-server-ip=192.168.123.164 \
 --display-mode=immersive \
 --network-interface enp45s0
```
### G1側PC
```code
source ~/miniconda3/etc/profile.d/conda.sh
conda activate teleimager
```
```code
cd ~/teleimager
teleimager-server --rs
```

## 無線 sshによる接続
### ローカルPCからg1内のPCにssh接続
内部PCのwlan0のipアドレスを確認
```code
ssh unitree@10.10.129.69
```
ros:foxy(1) noetic(2) ?と聞かれるのでCtrl+c \
2つのターミナルで起動
### ターミナル1
```code
tmux new -s img
```
ros:foxy(1) noetic(2) ?と聞かれるのでCtrl+c
```code
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
```
```code
cd ~/teleimager
python -m teleimager.image_server --rs
```
### ターミナル2
```code
tmux new -s img
```
ros:foxy(1) noetic(2) ?と聞かれるのでCtrl+c
```code
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
```
```code
cd ~/xr_teleoperate/teleop
python teleop_hand_and_arm.py \
    --input-mode=controller \
    --arm G1_23 \
    --ee dex3 \
    --network-interface eth0 \
    --img-server-ip 127.0.0.1 \
    --ipc
```


