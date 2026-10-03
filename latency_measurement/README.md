# XR入力―ロボットsubscriber 遅延計測環境

ブラウザからDocker内ROS 2 subscriberまでの時刻を同じsequenceで記録する

## 計測経路

```text
Questブラウザ
  browser_event_ns       VuerがCONTROLLER_MOVEをWSSへ送る時刻
        ↓ WSS（インターネット）
XR teleop PC
  xr_receive_ns          TeleVuer handlerがイベントを受けた時刻
  xr_send_ns             ロボット宛UDPを送る直前の時刻
        ↓ UDP（VPN推奨）
ロボット内部PC
  bridge_receive_ns      UDP bridgeが受けた時刻
        ↓ ROS 2
Docker subscriber
  subscriber_receive_ns  callback開始時刻
```

起動前・起動時にNTP方式の往復計測を行い、ブラウザ→XR PCとXR PC→ロボットPCの時計オフセットを補正します。CSVの`*_raw_ms`は補正前、それ以外は補正後です。ネットワーク経路が大きく非対称な場合は往復推定にも誤差が残ります。

Vuerの現在の実装ではブラウザ時刻はWebXRハードウェアサンプルそのものではなく、30 Hzの `CONTROLLER_MOVE` をWSSへ送る時刻です。そのため、物理入力からブラウザ送信まで最大約33 msの待ち時間はこのCSVに含まれません。

## ファイル

- `teleop/teleop_hand_and_arm_button.py`: 時刻付き送信を加えた遠隔操作プログラム
- `teleop/televuer/`: ブラウザ時刻とXR PC受信時刻を取り出すコピー版TeleVuer
- `teleop/xr_button_bridge_node.py`: UDPから計測用ROS 2トピックへのブリッジ
- `robot/timed_button_subscriber.py`: Docker内でCSVを記録するsubscriber
- `browser_clock_sync_server.py`: QuestブラウザとXR PCの時計同期ページ
- `clock_sync.py`: XR PCとロボットPCのUDP時計同期
- `analyze_csv.py`: min/mean/p50/p95/p99/maxとsequence欠落を集計
- `camera_latency_node.py`: Docker側のカメラ計測サーバー起動・CSV保存・集計（単体動作）
- `analyze_camera_csv.py`: ホスト側でカメラCSVだけを集計する補助スクリプト
- `send_test_packets.py`: XRを起動せず通信経路を確認するテスト送信器

## 1. 基本の時計同期

XR PCとロボット内部PCの両方でchronyを有効にし、測定直前に状態を確認します。

```bash
chronyc tracking
chronyc sources -v
```

Questは日付と時刻の自動設定を有効にします。chronyに加えて、以下のアプリケーション内同期を測定ごとに実行します。

## 2. ネットワーク

XR PCとロボット内部PCの間はWireGuardやTailscale等のVPNを推奨します。UDP 9870（計測）と9871（時計同期）をインターネットへ直接公開せず、`--button-bridge-host`にはロボット側VPN IPを指定します。

Dockerでbridgeとsubscriberを実行する場合は、ROS 2 discoveryとUDP受信を簡単にするためhost networkを推奨します。

```bash
docker run --network host ...
```

bridgeをホスト側、subscriberだけをDocker側で動かす場合も、Dockerをhost networkにするか、使用中のROS 2 DDSに合わせてネットワーク設定を行います。bridgeとsubscriberの`ROS_DOMAIN_ID`は同じ値にしてください。

## 3. ロボット側bridge

`xr_button_bridge_node.py`は単体で動作します。コンテナへはこの1ファイルだけコピーすればよく、`latency_protocol.py`や`clock_sync.py`は不要です。コンテナ側にはROS 2の`rclpy`と`std_msgs`が必要です。

```bash
# ホストからコンテナへコピー
docker cp latency_measurement/teleop/xr_button_bridge_node.py \
  CONTAINER_NAME:/tmp/xr_button_bridge_node.py

# コンテナ内で実行
python3 /tmp/xr_button_bridge_node.py \
  --host 0.0.0.0 \
  --port 9870 \
  --sync-port 9871
```

配信トピックは次のとおりです。

```text
/teleop/button/right_b_timed  std_msgs/msg/Int64MultiArray
/teleop/button/left_y_timed   std_msgs/msg/Int64MultiArray
/right_button                 std_msgs/msg/Bool（既存互換・エッジのみ）
/left_button                  std_msgs/msg/Bool（既存互換・エッジのみ）
```

## 4. Docker内subscriber

別ターミナルで実行します。

```bash
cd /path/to/xr_teleoperate
python latency_measurement/robot/timed_button_subscriber.py \
  --output latency_measurement/logs/run01.csv \
  --log-every 30
```

## 5. QuestブラウザとXR PCの時計同期

XR PCで時計同期ページを起動します。TeleVuerと同じ証明書が既定で使われます。

```bash
cd /path/to/xr_teleoperate
python latency_measurement/browser_clock_sync_server.py \
  --host 0.0.0.0 \
  --port 8013
```

Questブラウザから次を開きます。インターネット越しの場合は、8012と同様に到達できる公開ホスト名・リバースプロキシ・VPN等を使用してください。

```text
https://XR_PC_ADDRESS:8013/
```

30回の往復計測後に「同期完了」と表示され、次のファイルが作成されます。

```text
latency_measurement/runtime/browser_clock_offset.json
```

最小RTTの5サンプルから中央値を採用します。このファイルは10分で期限切れになるため、各測定の直前に同期してください。同期ページのサーバーは、ファイル保存後に停止して構いません。

## 6. XR teleop PC

元の起動コマンドのスクリプト部分をコピー版に変え、ロボットのVPN IPを指定します。その他のarm、ee、image、network引数は実環境の値を使用してください。

```bash
cd /path/to/xr_teleoperate
python latency_measurement/teleop/teleop_hand_and_arm_button.py \
  --input-mode controller \
  --arm G1_23 \
  --motion \
  --network-interface eth0 \
  --img-server-ip ROBOT_IMAGE_IP \
  --button-bridge-host ROBOT_VPN_IP \
  --button-bridge-port 9870 \
  --clock-sync-port 9871 \
  --clock-sync-samples 20
```

起動時にブラウザ同期ファイルを読み、続いてロボットbridgeと20回のUDP往復同期を行います。bridgeを先に起動してください。同期に失敗した場合は計測パケットを送信しません。意図的に補正なしで試す場合だけ`--clock-sync-disable`を指定します。

このスクリプトはコピー版TeleVuerを優先して読み込みます。元の `teleop/` と、環境にインストール済みのTeleVuerは変更しません。teleop起動後、Questで通常のWebXR URLを開きます。

## 7. XRなしの疎通確認

```bash
python latency_measurement/send_test_packets.py ROBOT_VPN_IP \
  --port 9870 \
  --sync-port 9871 \
  --count 100 \
  --hz 30
```

bridgeに新しいsessionが表示され、subscriberのCSVに100 sequence分の左右各行が入れば経路は正常です。

テスト送信器もロボットbridgeとのUDP時計同期を行います。ブラウザは介さないため、ブラウザ→XRの補正値だけ0です。

## 8. 集計

```bash
python latency_measurement/analyze_csv.py latency_measurement/logs/run01.csv
```

`missing_updates`はブラウザイベントsequenceの飛びです。これはWAN上のUDP損失だけでなく、XR PCのメインループが新しいイベントで上書きされた場合も含む「subscriberまで届かなかった更新数」です。

遠隔操作では平均値よりもp95、p99、最大値と欠落率を重視してください。時計同期が十分でない場合でも、`xr_processing_ms`と`ros_delivery_ms`は有効です。

## CSVの時計関連列

```text
browser_to_xr_offset_ns  XR時計 - ブラウザ時計
xr_to_robot_offset_ns    ロボット時計 - XR時計
browser_to_xr_raw_ms     補正前
browser_to_xr_ms         補正後
wan_raw_ms               補正前
wan_ms                   補正後
end_to_end_raw_ms        補正前
end_to_end_ms            2区間とも補正後
```

補正後の遅延が継続的に負になる場合は、経路の非対称性、古い同期ファイル、端末時計の急な補正を疑ってください。

## カメラ映像遅延の計測

`camera_latency_node.py`はDocker側で単体動作します。コンテナへはこの1ファイルだけコピーすればよく、`analyze_camera_csv.py`、`latency_protocol.py`、コピー版`teleimager`は不要です。ただし、コンテナには通常の画像サーバーとして動作する`teleimager`と、そのカメラ・WebRTC依存パッケージがインストール済みである必要があります。

ホストからコンテナへコピーし、このファイル経由で画像サーバーを起動します。`--rs`など未認識の引数は、そのまま`teleimager.image_server`へ渡されます。

```bash
# ホスト側
docker cp latency_measurement/camera_latency_node.py \
  CONTAINER_NAME:/tmp/camera_latency_node.py

# コンテナ内（/logsは書き込み可能なvolume等に変更可）
python3 /tmp/camera_latency_node.py \
  --latency-log-dir /logs \
  --rs
```

この起動方法ではWebRTC publisherへフレームを渡す直前に、映像左上へ448×16 pixelの二値タイムスタンプを付加します。元の`teleimager`ファイルは書き換えません。

Questブラウザでhead cameraのWebRTCポートを直接開き、`Start`を押します。既定設定ではhead cameraは60001です。

```text
https://ROBOT_CAMERA_ADDRESS:60001/
```

ページはブラウザ↔ロボット画像サーバーの時計を20回往復同期した後、各表示フレームのマーカーを読みます。画面には現在値、p50、p95が表示され、30フレームごとにロボット側へCSVが保存されます。

```text
/logs/xr_camera_latency_60001.csv
```

同じ1ファイルで集計できます。

```bash
python3 /tmp/camera_latency_node.py \
  --analyze /logs/xr_camera_latency_60001.csv
```

この値に含まれるもの:

- WebRTC publisherへフレームを渡してからエンコードされるまで
- WebRTCエンコード
- WAN伝送
- Questブラウザの受信・ジッターバッファ・デコード
- `requestVideoFrameCallback`で表示処理へ渡るまで

VuerのWebRTC planeによる最終XR合成時間は、直接の計測ページとは別処理なので含まれません。また、カメラ露光開始からPythonがフレームを受け取るまでと、teleimager内部でWebRTC publisherへ渡される前の時間も含まれません。

計測終了後はこのプロセスを停止し、通常の`teleimager.image_server`起動方法へ戻してください。
