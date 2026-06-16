import * as THREE from 'three'
import * as TWEEN from '@tweenjs/tween.js'
import type { AnimationType, AnimationParams } from '@/types'

// ============ 相机状态接口 ============

interface CameraState {
  x: number
  y: number
  z: number
  lookX: number
  lookY: number
  lookZ: number
}

// ============ 动画引擎 ============
//
// 基于 @tweenjs/tween.js 的相机动态轨迹动画引擎
//
// 模板:
//   TPL-001 swing:  正弦函数 Math.sin(time) * amplitude → 相机 X 轴水平摇摆
//   TPL-002 zoom:   Z 轴缓慢推进/拉远 → 呼吸感 3D 变焦
//   TPL-003 rotate: 环绕 Y 轴旋转
//   TPL-004 parallax: 水平视差平移
//   TPL-005 dolly:  前进推进 + 景深
//
// 用法:
//   const engine = new AnimationEngine(camera)
//   engine.play('swing', params)
//   engine.update(deltaMs)  // 在 R3F useFrame 中调用
//   engine.stop()

export class AnimationEngine {
  private camera: THREE.PerspectiveCamera
  private activeTween: TWEEN.Tween<CameraState> | null = null
  private currentState: CameraState
  private _isPlaying = false
  private _currentType: AnimationType | null = null
  private _params: AnimationParams | null = null

  // 默认相机位置
  private static readonly DEFAULT_POSITION = new THREE.Vector3(0, 0, 2.5)
  private static readonly DEFAULT_LOOK_AT = new THREE.Vector3(0, 0, 0)

  constructor(camera: THREE.PerspectiveCamera) {
    this.camera = camera
    this.currentState = this._getCameraState()
  }

  // ---- 播放动画 ----

  play(type: AnimationType, params: AnimationParams) {
    // 如果已经在播放相同类型和参数，不重复创建
    if (this._isPlaying && this._currentType === type && this._params === params) {
      return
    }

    this.stop()
    this._currentType = type
    this._params = params
    this._isPlaying = true

    // 重置相机到默认位置
    this._resetCamera()
    this.currentState = this._getCameraState()

    // 根据模板创建 Tween
    const tween = this._createTween(type, params)
    if (tween) {
      this.activeTween = tween.start()
    }
  }

  // ---- 停止动画 ----

  stop() {
    if (this.activeTween) {
      this.activeTween.stop()
      this.activeTween = null
    }
    this._isPlaying = false
    this._resetCamera()
  }

  // ---- 每帧更新 (在 useFrame 中调用) ----

  update(deltaMs?: number) {
    if (!this._isPlaying) return
    TWEEN.update(deltaMs)
    this._applyState()
  }

  // ---- 状态查询 ----

  get isPlaying() { return this._isPlaying }
  get currentType() { return this._currentType }

  // ---- 销毁 ----

  dispose() {
    this.stop()
  }

  // ============ 内部方法 ============

  private _getCameraState(): CameraState {
    return {
      x: this.camera.position.x,
      y: this.camera.position.y,
      z: this.camera.position.z,
      lookX: 0,
      lookY: 0,
      lookZ: 0,
    }
  }

  private _resetCamera() {
    this.camera.position.copy(AnimationEngine.DEFAULT_POSITION)
    this.camera.lookAt(AnimationEngine.DEFAULT_LOOK_AT)
  }

  private _applyState() {
    this.camera.position.set(this.currentState.x, this.currentState.y, this.currentState.z)
    this.camera.lookAt(this.currentState.lookX, this.currentState.lookY, this.currentState.lookZ)
  }

  // ---- 创建 Tween 动画 ----

  private _createTween(type: AnimationType, params: AnimationParams): TWEEN.Tween<CameraState> | null {
    const amp = params.amplitude
    const duration = params.duration
    const loop = params.loop

    switch (type) {
      case 'swing':
        return this._createSwingTween(amp, duration, loop)
      case 'zoom':
        return this._createZoomTween(amp, duration, loop)
      case 'rotate':
        return this._createRotateTween(amp, duration, loop)
      case 'parallax':
        return this._createParallaxTween(amp, duration, loop)
      case 'dolly':
        return this._createDollyTween(amp, duration, loop)
      default:
        return null
    }
  }

  // ---- TPL-001: 摇摆模板 ----
  // 正弦函数 Math.sin(time) * amplitude → 相机 X 轴水平摇摆

  private _createSwingTween(amp: number, duration: number, loop: boolean): TWEEN.Tween<CameraState> {
    const halfDuration = duration / 2

    // 正弦曲线: 0 → +amplitude → 0 → -amplitude → 0
    const toRight: CameraState = {
      x: amp * 0.3,
      y: amp * 0.05,
      z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const toLeft: CameraState = {
      x: -amp * 0.3,
      y: -amp * 0.03,
      z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const center: CameraState = {
      x: 0, y: 0, z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const tweenRight = new TWEEN.Tween(this.currentState)
      .to(toRight, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    const tweenLeft = new TWEEN.Tween(this.currentState)
      .to(toLeft, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    const tweenCenter = new TWEEN.Tween(this.currentState)
      .to(center, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    // 链式: center → right → center → left → center → ...
    tweenCenter.chain(tweenRight)
    tweenRight.chain(tweenCenter)
    tweenCenter.chain(tweenLeft)
    tweenLeft.chain(tweenCenter)

    if (!loop) {
      tweenLeft.chain(new TWEEN.Tween(this.currentState).to(center, halfDuration))
    }

    return tweenCenter
  }

  // ---- TPL-002: 缩放模板 ----
  // Z 轴缓慢推进/拉远 → 呼吸感 3D 变焦

  private _createZoomTween(amp: number, duration: number, loop: boolean): TWEEN.Tween<CameraState> {
    const halfDuration = duration / 2

    const zoomIn: CameraState = {
      x: 0, y: 0,
      z: 2.5 - amp * 0.4,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const zoomOut: CameraState = {
      x: 0, y: 0,
      z: 2.5 + amp * 0.3,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const center: CameraState = {
      x: 0, y: 0, z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const tweenIn = new TWEEN.Tween(this.currentState)
      .to(zoomIn, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    const tweenOut = new TWEEN.Tween(this.currentState)
      .to(zoomOut, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    const tweenCenter = new TWEEN.Tween(this.currentState)
      .to(center, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    // 链式: center → zoomIn → center → zoomOut → center → ...
    tweenCenter.chain(tweenIn)
    tweenIn.chain(tweenCenter)
    tweenCenter.chain(tweenOut)
    tweenOut.chain(tweenCenter)

    if (!loop) {
      tweenOut.chain(new TWEEN.Tween(this.currentState).to(center, halfDuration))
    }

    return tweenCenter
  }

  // ---- TPL-003: 环绕旋转模板 ----

  private _createRotateTween(amp: number, duration: number, loop: boolean): TWEEN.Tween<CameraState> {
    const steps = 8
    const stepDuration = duration / steps
    const radius = 2.5
    const angleAmp = amp * 0.4  // 最大旋转角度 (弧度)

    let chain: TWEEN.Tween<CameraState> | null = null
    let first: TWEEN.Tween<CameraState> | null = null

    for (let i = 0; i <= steps; i++) {
      const angle = (i / steps) * Math.PI * 2  // 完整一圈
      const x = Math.sin(angle) * radius * Math.sin(angleAmp)
      const z = Math.cos(angle) * radius

      const target: CameraState = {
        x, y: 0, z,
        lookX: 0, lookY: 0, lookZ: 0,
      }

      const tween = new TWEEN.Tween(this.currentState)
        .to(target, stepDuration)
        .easing(TWEEN.Easing.Sinusoidal.InOut)

      if (!first) first = tween
      if (chain) chain.chain(tween)
      chain = tween
    }

    // 循环: 最后一步链回第一步
    if (loop && chain && first) {
      chain.chain(first)
    }

    return first!
  }

  // ---- TPL-004: 平行视差模板 ----

  private _createParallaxTween(amp: number, duration: number, loop: boolean): TWEEN.Tween<CameraState> {
    const halfDuration = duration / 2

    const toRight: CameraState = {
      x: amp * 0.4,
      y: 0, z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const toLeft: CameraState = {
      x: -amp * 0.4,
      y: 0, z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const center: CameraState = {
      x: 0, y: 0, z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const tweenRight = new TWEEN.Tween(this.currentState)
      .to(toRight, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    const tweenLeft = new TWEEN.Tween(this.currentState)
      .to(toLeft, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    const tweenCenter = new TWEEN.Tween(this.currentState)
      .to(center, halfDuration)
      .easing(TWEEN.Easing.Sinusoidal.InOut)

    tweenCenter.chain(tweenRight)
    tweenRight.chain(tweenCenter)
    tweenCenter.chain(tweenLeft)
    tweenLeft.chain(tweenCenter)

    if (!loop) {
      tweenLeft.chain(new TWEEN.Tween(this.currentState).to(center, halfDuration))
    }

    return tweenCenter
  }

  // ---- TPL-005: 推进穿越模板 ----

  private _createDollyTween(amp: number, duration: number, loop: boolean): TWEEN.Tween<CameraState> {
    const halfDuration = duration / 2

    const pushIn: CameraState = {
      x: 0, y: 0,
      z: 2.5 - amp * 0.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const pullOut: CameraState = {
      x: 0, y: 0,
      z: 2.5 + amp * 0.2,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const center: CameraState = {
      x: 0, y: 0, z: 2.5,
      lookX: 0, lookY: 0, lookZ: 0,
    }

    const tweenIn = new TWEEN.Tween(this.currentState)
      .to(pushIn, halfDuration)
      .easing(TWEEN.Easing.Cubic.InOut)

    const tweenOut = new TWEEN.Tween(this.currentState)
      .to(pullOut, halfDuration)
      .easing(TWEEN.Easing.Cubic.InOut)

    const tweenCenter = new TWEEN.Tween(this.currentState)
      .to(center, halfDuration)
      .easing(TWEEN.Easing.Cubic.InOut)

    tweenCenter.chain(tweenIn)
    tweenIn.chain(tweenCenter)
    tweenCenter.chain(tweenOut)
    tweenOut.chain(tweenCenter)

    if (!loop) {
      tweenOut.chain(new TWEEN.Tween(this.currentState).to(center, halfDuration))
    }

    return tweenCenter
  }
}
