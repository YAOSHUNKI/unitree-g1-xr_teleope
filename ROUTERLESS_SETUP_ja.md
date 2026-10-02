# xr_teleop ルータレス完全ワイヤレス構成 セットアップ手順

Unitree G1 の内部PC (PC2) を Wi-Fi アクセスポイント化し、外部 Wi-Fi ルータ無しで XR ヘッドセットから teleop を実行する構成の記録。

対象: `xr_teleoperate` (Unitree公式) を PC2 上で完結させ、XRヘッドセット (PICO/Quest等) と G1 だけで動かす。

---

## 1. 構成概要

```
┌──────────────────────────────────────────────────────┐
│  G1 本体                                             │
│  ┌────────────────────────────────────────────────┐  │
│  │ PC2 (内部PC, Ubuntu)                           │  │
│  │  eth1 : 192.168.123.164 → G1 低レベル DDS      │  │
│  │  wlan0: 10.42.0.1 (AP: SSID=G1-AP, 5GHz ch36) │  │
│  │  ├─ teleimager (画像サービス)                  │  │
│  │  └─ teleop_hand_and_arm.py                     │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
              │
              │ Wi-Fi 5GHz (W52 ch36)
              ▼
      ┌────────────────┐
      │ XR Headset     │ 10.42.0.x
      │ (PICO / Quest) │
      └────────────────┘
```

- **外部ルータ不要**: PC2 の内蔵 Wi-Fi を AP モードにして、XRヘッドセットが直接繋がる
- **Host マシン不要**: teleop 本体・teleimager・vuer サーバをすべて PC2 上で動かす
- **G1 内部 DDS 通信は `eth1` (有線)** で従来通り

---

## 2. PC2 の Wi-Fi AP 化

### 2.1 事前確認: 内蔵 Wi-Fi が AP モード対応か

```bash
iw list | grep -A5 "Supported interface modes"
```

`* AP` が含まれていること。今回の PC2 は Wi-Fi 6 (HE) 対応、5GHz W52 (ch36/40/48) が使用可能なことを確認。

### 2.2 AP セットアップ (NetworkManager)

```bash
sudo nmcli con delete g1ap 2>/dev/null

sudo nmcli con add type wifi ifname wlan0 con-name g1ap autoconnect yes ssid G1-AP
sudo nmcli con modify g1ap \
  802-11-wireless.mode ap \
  802-11-wireless.band a \
  802-11-wireless.channel 36 \
  ipv4.method shared \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "unitree1234"

sudo nmcli con up g1ap
```

- `band a` + `channel 36` = 5GHz W52 (日本の電波法で APとして起動可能な帯域)
- `ipv4.method shared` で dnsmasq (DHCP) + NAT が自動起動、クライアントは 10.42.0.x を取得

### 2.3 動作確認

```bash
iw dev wlan0 info                        # type AP, channel 36
ip -4 addr show wlan0                    # 10.42.0.1/24
sudo iptables -t nat -L POSTROUTING      # MASQUERADE 10.42.0.0/24 !10.42.0.0/24
cat /proc/sys/net/ipv4/ip_forward        # 1
```

### ⚠️ 注意: AP 起動で SSH セッションが切れる

wlan0 経由で SSH していた場合、AP モードに切り替わった瞬間に元のネットワークから切断される。復旧は次のいずれか:

- **有線経由**: 別マシンから `ssh unitree@192.168.123.164` (eth1 経由)
- **G1-AP 経由**: 自分の端末を G1-AP に接続してから `ssh unitree@10.42.0.1`
- **物理コンソール**: G1 本体にモニタ+USBキーボード直挿し

以降の作業は **有線 or G1-AP 経由の SSH** で行う。

---

## 3. PC2 に xr_teleoperate 環境を構築

### 3.1 リポジトリ配置

```bash
(base) unitree@PC2:~$ conda create -n tv python=3.10 -y
(base) unitree@PC2:~$ conda activate tv

(tv) unitree@PC2:~$ git clone https://github.com/unitreerobotics/xr_teleoperate.git
(tv) unitree@PC2:~$ cd xr_teleoperate
(tv) unitree@PC2:~/xr_teleoperate$ git submodule update --init --depth 1

# サブモジュール
(tv) unitree@PC2:~/xr_teleoperate$ cd teleop/teleimager    && pip install -e . --no-deps
(tv) unitree@PC2:~/xr_teleoperate$ cd ../televuer          && pip install -e .
(tv) unitree@PC2:~/xr_teleoperate$ cd ../robot_control/dex-retargeting && pip install -e .
(tv) unitree@PC2:~/xr_teleoperate$ cd ../../.. && pip install -r requirements.txt

# unitree_sdk2_python
(tv) unitree@PC2:~$ git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
(tv) unitree@PC2:~/unitree_sdk2_python$ pip install -e .
```

---

## 4. SAN 付き証明書の生成

XRヘッドセットからの HTTPS/WebSocket アクセス用。**wlan0 の IP (10.42.0.1) を SAN に含めることが必須**。含めないと Quest/PICO ブラウザで証明書エラーになる。

```bash
(tv) unitree@PC2:~$ cd ~/xr_teleoperate/teleop/televuer

# 既存バックアップ
mv cert.pem cert.pem.bak 2>/dev/null
mv key.pem  key.pem.bak  2>/dev/null

# rootCA
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 365 \
  -out rootCA.pem -subj "/CN=xr-teleoperate"

# server key + CSR
openssl genrsa -out key.pem 2048
openssl req -new -key key.pem -out server.csr -subj "/CN=g1-teleop"

# SAN 設定
cat > server_ext.cnf <<'EOF'
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
IP.1 = 10.42.0.1
IP.2 = 192.168.123.164
IP.3 = 127.0.0.1
EOF

# 署名
openssl x509 -req -in server.csr -CA rootCA.pem -CAkey rootCA.key \
  -CAcreateserial -out cert.pem -days 365 -sha256 -extfile server_ext.cnf

# 確認
openssl x509 -in cert.pem -noout -text | grep -A4 "Subject Alternative"

# 設置
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/

# ファイアウォール開放
sudo ufw allow 8012    # vuer
sudo ufw allow 60001   # teleimager WebRTC
```

**`rootCA.pem` を XR ヘッドセットに転送してインストール**:

```bash
# PC2 上で簡易 HTTP サーバ起動
cd ~/xr_teleoperate/teleop/televuer
python -m http.server 8080
```

XRヘッドセットのブラウザで `http://10.42.0.1:8080/rootCA.pem` にアクセス → ダウンロード → 設定 → セキュリティ → 認証情報 → CA証明書としてインストール。

---

## 5. teleimager (画像サービス) の起動

### 5.1 RealSense を使う場合 (G1 頭部カメラ想定)

`--rs` フラグ必須。省略すると `Camera head_camera failed to initialize` エラー。

```bash
(tv) unitree@PC2:~$ cd ~/xr_teleoperate/teleop/teleimager
(tv) unitree@PC2:~/xr_teleoperate/teleop/teleimager$ teleimager-server --rs
```

### 5.2 カメラ設定確認

初回は接続カメラを一覧:

```bash
teleimager-server --cf
```

その情報を `cam_config_server.yaml` に反映してから `--rs` 付きで本起動。

---

## 6. teleop 本体の起動

### 6.1 ネットワークIF名を確認

**⚠️ 重要**: PC2 のインターフェース名は環境依存。`eth0` は NO-CARRIER で使えず、実際に G1 内部 LAN に繋がっているのは **`eth1`** だった。

```bash
ip -br link show
```

`UP` かつ `192.168.123.164/24` が付いている IF を確認。今回は `eth1`。

### 6.2 起動コマンド

別ターミナル (`ssh unitree@10.42.0.1` を追加で1本) で:

```bash
(tv) unitree@PC2:~$ cd ~/xr_teleoperate/teleop
(tv) unitree@PC2:~/xr_teleoperate/teleop$ python teleop_hand_and_arm.py \
    --input-mode=controller \
    --motion \
    --arm G1_23 \
    --network-interface eth1 \
    --img-server-ip 127.0.0.1
```

パラメータ:

| フラグ | 意味 |
| --- | --- |
| `--network-interface eth1` | CycloneDDS を eth1 (G1 内部 LAN) にバインド。**wlan0 側に DDS が漏れないように必ず指定** |
| `--img-server-ip 127.0.0.1` | teleimager も同じ PC2 で動くのでループバック指定 |
| `--motion` | R3 リモコンで歩行制御を有効化 |
| `--arm G1_23` | G1 (23 DoF) 構成 |
| `--input-mode controller` | XR コントローラーで制御 (ハンドトラッキングなら `hand`) |

`--headless` は PC2 にディスプレイが無い場合に追加。

---

## 7. XR ヘッドセット側の接続手順

1. Wi-Fi で **`G1-AP`** に接続 (パスワード `unitree1234`)
2. 割り当てられた IP を確認 (10.42.0.x)
3. `rootCA.pem` インストール済みであることを確認
4. **WebRTC 使用時** のみ: ブラウザで `https://10.42.0.1:60001` → `Start`
5. ブラウザで **`https://10.42.0.1:8012/?ws=wss://10.42.0.1:8012`** を開く
6. `Virtual Reality` ボタン → VR セッション開始
7. PC2 のターミナルに `websocket is connected. id:...` が出れば成功
8. 腕を初期姿勢に近づけて PC2 ターミナルで **r** キー → teleop 開始
9. **s** キーでデータ記録開始/停止 (`--record` 指定時)
10. **q** キーで終了

---

## 8. トラブルシューティング (今回ハマった点)

### 8.1 `sudo nmcli con up g1ap` で SSH が切れる

原因: wlan0 経由でSSHしていた。AP モードに切り替わると元のWi-Fi接続が切れる。

対策: 有線 (192.168.123.164) or G1-AP 経由で再接続、または物理コンソール。今後は wlan0 経由の SSH は使わず、有線か G1-AP 経由で運用する。

### 8.2 `iw dev wlan0 info` で width が 20 MHz にしかならない

原因: NetworkManager は AP モードの帯域幅を直接指定できない。

対策: 実用に耐えるなら 20MHz でOK。80MHz に広げたい場合は hostapd 直叩き設定に切り替え (`hw_mode=a`, `channel=36`, `ieee80211ax=1`, `he_oper_chwidth=1` 等)。

### 8.3 teleimager が `Camera head_camera failed to initialize`

原因: `cam_config_server.yaml` で RealSense を指定しているのに `--rs` フラグ無しで起動。

対策: `teleimager-server --rs` で起動。

### 8.4 teleop で `eth0: does not match an available interface`

原因: PC2 のインターフェース名は `eth0` ではなく `eth1`。

対策: `ip -br link show` で実IF名を確認して `--network-interface eth1` を指定。

### 8.5 XR ブラウザで証明書エラー

原因: 既存の `cert.pem` に SAN が入っておらず、IP アドレス直打ちアクセスに対応していなかった。

対策: セクション 4 の手順で SAN 付きで再生成し、`rootCA.pem` をヘッドセットにインストール。

---

## 9. 運用上の注意

- **DDS を wlan0 に漏らさない**: `--network-interface eth1` を必ず指定。無指定だと DDS が全 IF で multicast し、無線側の画像帯域を食う。
- **代替の CycloneDDS 環境変数**:
  ```bash
  export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="eth1"/></Interfaces></General></Domain></CycloneDDS>'
  ```
- **PC2 の負荷**: teleop + teleimager + hostapd/NM を同時実行するのでCPU/GPU/サーマルに注意。特に画像複数ch + WebRTC + DDS 1kHz は Orin NX でも余裕は少ない。
- **接続経路の使い分け**:
  - 開発・デバッグ時: 有線 SSH (192.168.123.164)
  - フィールド運用時: G1-AP 経由 SSH (10.42.0.1)
- **自動起動化**: 現場運用するなら `hostapd.service` + `teleimager.service` + `teleop.service` を systemd で常駐化。G1 電源投入だけで teleop 待機状態にできる。

---

## 10. 接続情報まとめ

| 項目 | 値 |
| --- | --- |
| SSID | `G1-AP` |
| パスワード | `unitree1234` |
| 帯域 | 5GHz W52 ch36 |
| AP側IP (PC2 wlan0) | `10.42.0.1` |
| G1 内部LAN側IP (PC2 eth1) | `192.168.123.164` |
| G1 MCU | `192.168.123.161` |
| vuer URL | `https://10.42.0.1:8012/?ws=wss://10.42.0.1:8012` |
| teleimager WebRTC URL | `https://10.42.0.1:60001` |
| SSH (無線) | `ssh unitree@10.42.0.1` |
| SSH (有線) | `ssh unitree@192.168.123.164` |
