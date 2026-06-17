/** Camera Path Engine - Level 3 相机轨迹插值引擎
 *
 * Immersity 的本质不是"图动"，而是相机在"虚拟空间里移动"。
 * Level 3 增强:
 *   - orbit / pan / dolly / easePath 四种运动类型
 *   - 关键帧 timeline 系统
 *   - Catmull-Rom 样条插值 (平滑曲线)
 *   - FOV 动画
 */

import * as THREE from 'three'

// ============ 类型定义 ============

export interface CameraKeyframe {
  time: number          // 时间点 (秒)
  position: [number, number, number]  // [x, y, z]
  target: [number, number, number]    // lookAt 目标
  fov?: number         // 可选 FOV 变化
  easing?: EasingType
}

export type EasingType = 'linear' | 'ease-in' | 'ease-out' | 'ease-in-out' | 'sinusoidal' | 'catmull-rom'

export type MotionType = 'orbit' | 'pan' | 'dolly' | 'easePath'

export interface CameraPath {
  id: string
  name: string
  duration: number
  loop: boolean
  motionType: MotionType
  keyframes: CameraKeyframe[]
}

// ============ 预设轨迹模板 ============

export const PRESET_PATHS: Record<string, CameraPath> = {
  cinematic_pan: {
    id: 'cinematic_pan',
    name: '电影摇摄',
    duration: 6.0,
    loop: true,
    motionType: 'pan',
    keyframes: [
      { time: 0.0, position: [-1.5, 0.1, 5],   target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 1.5, position: [0, 0, 5],         target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 3.0, position: [1.5, -0.1, 5],    target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 4.5, position: [0, 0, 5],         target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 6.0, position: [-1.5, 0.1, 5],    target: [0, 0, 0], easing: 'sinusoidal' },
    ],
  },

  gentle_orbit: {
    id: 'gentle_orbit',
    name: '缓慢环绕',
    duration: 8.0,
    loop: true,
    motionType: 'orbit',
    keyframes: [
      { time: 0.0, position: [1.5, 0.3, 4.5],   target: [0, 0, 0], easing: 'catmull-rom' },
      { time: 2.0, position: [0, 0.5, 4.2],      target: [0, 0, 0], easing: 'catmull-rom' },
      { time: 4.0, position: [-1.5, 0.3, 4.5],   target: [0, 0, 0], easing: 'catmull-rom' },
      { time: 6.0, position: [0, 0.1, 4.2],      target: [0, 0, 0], easing: 'catmull-rom' },
      { time: 8.0, position: [1.5, 0.3, 4.5],    target: [0, 0, 0], easing: 'catmull-rom' },
    ],
  },

  push_in: {
    id: 'push_in',
    name: '推进穿越',
    duration: 4.0,
    loop: true,
    motionType: 'dolly',
    keyframes: [
      { time: 0.0, position: [0, 0, 6],    target: [0, 0, 0], fov: 50, easing: 'ease-in-out' },
      { time: 2.0, position: [0, 0, 3.5],  target: [0, 0, 0], fov: 55, easing: 'ease-in-out' },
      { time: 4.0, position: [0, 0, 6],    target: [0, 0, 0], fov: 50, easing: 'ease-in-out' },
    ],
  },

  vertical_survey: {
    id: 'vertical_survey',
    name: '上下巡视',
    duration: 5.0,
    loop: true,
    motionType: 'pan',
    keyframes: [
      { time: 0.0, position: [0, -1.0, 5],  target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 1.25, position: [0, -0.3, 5], target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 2.5, position: [0, 0.5, 5],   target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 3.75, position: [0, -0.3, 5], target: [0, 0, 0], easing: 'sinusoidal' },
      { time: 5.0, position: [0, -1.0, 5],  target: [0, 0, 0], easing: 'sinusoidal' },
    ],
  },

  // Level 3 新增: 自由路径
  ease_path: {
    id: 'ease_path',
    name: '自由路径',
    duration: 6.0,
    loop: true,
    motionType: 'easePath',
    keyframes: [
      { time: 0.0, position: [-1.0, -0.3, 5.5], target: [0, 0, 0], fov: 50, easing: 'catmull-rom' },
      { time: 1.5, position: [0.5, 0.2, 4.5],   target: [0, 0, 0], fov: 52, easing: 'catmull-rom' },
      { time: 3.0, position: [1.0, -0.1, 5.0],   target: [0, 0, 0], fov: 48, easing: 'catmull-rom' },
      { time: 4.5, position: [-0.3, 0.3, 4.8],   target: [0, 0, 0], fov: 51, easing: 'catmull-rom' },
      { time: 6.0, position: [-1.0, -0.3, 5.5],  target: [0, 0, 0], fov: 50, easing: 'catmull-rom' },
    ],
  },
}

// ============ Catmull-Rom 样条插值 ============

function catmullRom(
  p0: number, p1: number, p2: number, p3: number, t: number
): number {
  const t2 = t * t
  const t3 = t2 * t
  return 0.5 * (
    (2 * p1) +
    (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3
  )
}

function catmullRomVec3(
  points: THREE.Vector3[],
  t: number
): THREE.Vector3 {
  const n = points.length
  const scaledT = t * (n - 1)
  const i = Math.floor(scaledT)
  const frac = scaledT - i

  const p0 = points[Math.max(0, i - 1)]
  const p1 = points[Math.min(n - 1, i)]
  const p2 = points[Math.min(n - 1, i + 1)]
  const p3 = points[Math.min(n - 1, i + 2)]

  return new THREE.Vector3(
    catmullRom(p0.x, p1.x, p2.x, p3.x, frac),
    catmullRom(p0.y, p1.y, p2.y, p3.y, frac),
    catmullRom(p0.z, p1.z, p2.z, p3.z, frac),
  )
}

// ============ 轨迹插值引擎 ============

export class CameraPathEngine {
  private camera: THREE.PerspectiveCamera
  private currentPath: CameraPath | null = null
  private _isPlaying = false
  private _startTime = 0
  private _baseFov = 60
  private _basePosition = new THREE.Vector3(0, 0, 5)

  constructor(camera: THREE.PerspectiveCamera) {
    this.camera = camera
    this._baseFov = camera.fov
    this._basePosition.copy(camera.position)
  }

  play(pathId: string): void {
    this.currentPath = PRESET_PATHS[pathId]
    if (!this.currentPath) return
    this._isPlaying = true
    this._startTime = performance.now() / 1000
    this._baseFov = this.camera.fov
    this._basePosition.copy(this.camera.position)
  }

  stop(): void {
    this._isPlaying = false
    // Reset to base position
    this.camera.position.copy(this._basePosition)
    this.camera.fov = this._baseFov
    this.camera.updateProjectionMatrix()
  }

  update(): void {
    if (!this._isPlaying || !this.currentPath) return

    const elapsed = (performance.now() / 1000) - this._startTime
    const duration = this.currentPath.duration
    const t = this.currentPath.loop
      ? (elapsed % duration) / duration
      : Math.min(elapsed / duration, 1)

    const kf = this.interpolateKeyframes(this.currentPath.keyframes, t)

    // Apply based on motion type
    switch (this.currentPath.motionType) {
      case 'orbit':
        // Orbit: camera rotates around target
        this.camera.position.set(...kf.position)
        this.camera.lookAt(new THREE.Vector3(...kf.target))
        break

      case 'pan':
        // Pan: camera translates, always looking at center
        this.camera.position.set(...kf.position)
        this.camera.lookAt(new THREE.Vector3(...kf.target))
        break

      case 'dolly':
        // Dolly: camera moves forward/backward along Z
        this.camera.position.set(...kf.position)
        this.camera.lookAt(new THREE.Vector3(...kf.target))
        break

      case 'easePath':
        // easePath: Catmull-Rom smooth path
        this.camera.position.copy(kf.positionVec3 || new THREE.Vector3(...kf.position))
        this.camera.lookAt(new THREE.Vector3(...kf.target))
        break
    }

    if (kf.fov) {
      this.camera.fov = kf.fov
      this.camera.updateProjectionMatrix()
    }
  }

  private interpolateKeyframes(
    keyframes: CameraKeyframe[],
    t: number
  ): Omit<CameraKeyframe, 'time' | 'easing'> & { positionVec3?: THREE.Vector3 } {
    if (keyframes.length === 1) return keyframes[0]

    // Catmull-Rom interpolation for easePath
    if (this.currentPath?.motionType === 'easePath') {
      const positions = keyframes.map(kf => new THREE.Vector3(...kf.position))
      const targets = keyframes.map(kf => new THREE.Vector3(...kf.target))
      const posVec3 = catmullRomVec3(positions, t)
      const tgtVec3 = catmullRomVec3(targets, t)

      // FOV interpolation
      let fov: number | undefined
      const fovs = keyframes.map(kf => kf.fov).filter((f): f is number => f !== undefined)
      if (fovs.length > 0) {
        const idx = Math.min(Math.floor(t * (fovs.length - 1)), fovs.length - 2)
        const localT = (t * (fovs.length - 1)) - idx
        fov = fovs[idx] + (fovs[Math.min(idx + 1, fovs.length - 1)] - fovs[idx]) * localT
      }

      return {
        position: [posVec3.x, posVec3.y, posVec3.z],
        target: [tgtVec3.x, tgtVec3.y, tgtVec3.z],
        fov,
        positionVec3: posVec3,
      }
    }

    // Linear/eased interpolation for other motion types
    let prevKf = keyframes[0]
    let nextKf = keyframes[keyframes.length - 1]

    for (let i = 0; i < keyframes.length - 1; i++) {
      const k1 = keyframes[i]
      const k2 = keyframes[i + 1]
      const segmentStart = k1.time / this.currentPath!.duration
      const segmentEnd = k2.time / this.currentPath!.duration

      if (t >= segmentStart && t <= segmentEnd) {
        prevKf = k1
        nextKf = k2
        break
      }
    }

    const localT = (t - prevKf.time / this.currentPath!.duration) /
      ((nextKf.time - prevKf.time) / this.currentPath!.duration)

    const easedT = this.applyEasing(localT, nextKf.easing ?? 'linear')

    return {
      position: this.lerpArray(prevKf.position, nextKf.position, easedT),
      target: this.lerpArray(prevKf.target, nextKf.target, easedT),
      fov: prevKf.fov && nextKf.fov
        ? prevKf.fov + (nextKf.fov - prevKf.fov) * easedT
        : undefined,
    }
  }

  private applyEasing(t: number, type: string): number {
    switch (type) {
      case 'ease-in': return t * t
      case 'ease-out': return t * (2 - t)
      case 'ease-in-out': return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t
      case 'sinusoidal': return (1 - Math.cos(t * Math.PI)) / 2
      case 'catmull-rom': return t // Catmull-Rom handled separately
      default: return t
    }
  }

  private lerpArray(a: number[], b: number[], t: number): number[] {
    return a.map((v, i) => v + (b[i] - v) * t)
  }

  get isPlaying(): boolean {
    return this._isPlaying
  }
}
