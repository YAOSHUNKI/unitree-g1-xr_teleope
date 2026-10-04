# XR遅延計測（ROS・Dockerなし）

QuestブラウザからXR PCまでのコントローラー入力遅延と、ロボットPCからQuestブラウザまでのカメラ映像遅延を計測します。計測経路にROS 2、Docker、専用UDP bridgeは使用しません。

## 計測区間

コントローラー入力:

```text
Questブラウザ
  browser_event_ns  CONTROLLER_MOVEをWSSへ送る時刻
        ↓ WSS
XR PC
  xr_receive_ns     TeleVuerがイベントを受信した時刻
```

`browser_to_xr_ms`は、ブラウザとXR PCの時計差を補正した受信遅延です。Vuerは現在30 Hzでイベントを送るため、物理入力から次の送信タイミングまでの待ち時間（最大約33 ms）は含みません。

カメラ映像:

```text
ロボットPCのteleimager → WebRTC → Questブラウザの表示処理
```

## 使用ファイル

- `browser_clock_sync_server.py`: QuestブラウザとXR PCの時計同期
- `teleop/teleop_hand_and_arm_button.py`: teleop実行と入力遅延CSVの保存
- `analyze_input_latency_csv.py`: 入力遅延CSVの集計
- `teleop/teleimager/`: カメラ遅延マーカーを追加したコピー版teleimager
- `analyze_camera_csv.py`: カメラ遅延CSVの集計

## 1. 端末の時刻確認

XR PCとロボットPCで確認します。

```bash
chronyc tracking
chronyc sources -v
```

Questは「日付と時刻の自動設定」を有効にします。

## 2. QuestブラウザとXR PCの時計同期

XR PCで実行します。

```bash
cd /home/shunki/xr_teleoperate
python3 latency_measurement/browser_clock_sync_server.py \
  --host 0.0.0.0 \
  --port 8013
```

Questブラウザで次を開き、「同期完了」を確認します。

```text
https://XR_PC_ADDRESS:8013/
```

同期結果は`latency_measurement/runtime/browser_clock_offset.json`へ保存され、10分で期限切れになります。各計測の直前に同期してください。

## 3. ロボットPCで計測用カメラサーバーを起動

初回だけ、カメラサーバーの依存パッケージをインストールします。

```bash
cd /home/shunki/xr_teleoperate
python3 -m pip install -e "./latency_measurement/teleop/teleimager[server]"
python3 -m pip install pyrealsense2
```

Dockerではなく、カメラが接続されたロボットPC上で起動します。

```bash
cd /home/shunki/xr_teleoperate
export PYTHONPATH="$PWD/latency_measurement/teleop/teleimager/src${PYTHONPATH:+:$PYTHONPATH}"
export XR_CAMERA_LATENCY_PROBE=1
export XR_CAMERA_LATENCY_LOG_DIR="$PWD/latency_measurement/logs"

python3 -m teleimager.image_server --rs
```

`--rs`はRealSense用です。実際のカメラに合わせて通常使用している引数へ変更します。

## 4. XR PCで入力・カメラ同時計測を開始

XR PCで実行します。arm、ee、image、network引数は実環境に合わせます。`ROBOT_IMAGE_IP`には操作用Questからも到達可能なロボットPCのIPを指定します。

```bash
cd /home/shunki/xr_teleoperate
python3 latency_measurement/teleop/teleop_hand_and_arm_button.py \
  --input-mode controller \
  --arm G1_23 \
  --motion \
  --network-interface XR_PC_INTERFACE \
  --img-server-ip ROBOT_IMAGE_IP \
  --input-latency-output /home/shunki/xr_teleoperate/latency_measurement/logs/xr_input_latency_run01.csv
```

操作用Questでは、XR PCが配信するローカルVuerページ（通常は`https://XR_PC_ADDRESS:8012/`）だけを開きます。ホスト版`https://vuer.ai/`には計測JavaScriptが注入されないため使用しないでください。

カメラの60001番ページを別タブで開く必要はありません。ローカルVuerページが表示中のWebRTC映像を捕捉し、ロボットPCとの時計同期、映像マーカーの読み取り、カメラCSVへの送信を自動実行します。

同時に次の2ファイルが記録されます。

```text
XR PC:     latency_measurement/logs/xr_input_latency_run01.csv
ロボットPC: latency_measurement/logs/xr_camera_latency_60001.csv
```

## 5. 集計

XR PCで入力遅延と実効更新損失率を集計します。

```bash
python3 latency_measurement/analyze_input_latency_csv.py \
  latency_measurement/logs/xr_input_latency_run01.csv \
  --expected-hz 30
```

- `consumer_loss`: TeleVuer受信後に記録ループが取りこぼした更新率
- `estimated_end_to_end_loss`: QuestからCSV記録までの実効的な更新欠落率

WebXR入力はWSS（WebSocket/TCP）なので、これは純粋なIPパケット損失ではなく、ブラウザ停止、キューdrop、切断、ネットワーク遅延、受信側の取りこぼしを含む利用不能更新率です。

ロボットPCでカメラ遅延を集計します。

```bash
python3 latency_measurement/analyze_camera_csv.py \
  latency_measurement/logs/xr_camera_latency_60001.csv
```

カメラ遅延にはWebRTCエンコード、WAN伝送、操作用Questのジッターバッファ、デコード、Vuer内の`requestVideoFrameCallback`までが含まれます。Vuer planeの最終XR合成時間と、カメラ露光開始からPythonがフレームを取得するまでの時間は含みません。

終了後は画像サーバーを停止し、環境変数を解除します。

```bash
unset XR_CAMERA_LATENCY_PROBE
unset XR_CAMERA_LATENCY_LOG_DIR
```
