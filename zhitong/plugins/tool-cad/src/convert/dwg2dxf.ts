/**
 * DWG → DXF through the LibreDWG `dwg2dxf` executable (GPLv3). The plugin
 * only starts it as a separate process through `ctx.subprocess`; data crosses
 * the process boundary as argv paths, temporary files, and the exit code, and
 * nothing is linked. The executable can be replaced or removed; without it
 * only DWG input is unavailable.
 *
 * Lookup order: `Config.dwg2dxfPath` → `DWG2DXF_BIN` → the package's
 * `bin/<platform>-<arch>/dwg2dxf[.exe]` → `PATH`.
 *
 * Each conversion copies the input to an ASCII-named file inside a fresh
 * `mkdtemp` directory (the official win64 build opens paths with ANSI
 * `fopen`, so non-code-page Chinese paths fail), runs
 * `dwg2dxf -y -o out.dxf in.dwg` with the executable's directory as the
 * working directory (Windows DLL lookup) and as the library path, enforces a
 * timeout that terminates the provider-managed process range, rejects output
 * above the DXF size limit, and removes the directory afterwards.
 *
 * Source: tiangong-cad-viewer `tools/convert.mjs` (`resolveDwg2dxf`,
 * `dwgToDxf`) and `electron/main.cjs` (ASCII copy, size limit); `mkdtemp`,
 * timeout, and range termination added.
 * @module @zhitong/tool-cad/convert/dwg2dxf
 */
import { access, constants, copyFile, mkdtemp, readFile, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import type { SubprocessRuntime } from '@deepseek-ai/dsh-subprocess'
import { SubprocessExecutableNotFoundError } from '@deepseek-ai/dsh-subprocess'

/** Where the executable was found. */
export type Dwg2DxfSource = 'config' | 'env' | 'bundled' | 'path'

/** A located dwg2dxf executable. */
export interface Dwg2DxfBinary {
  path: string
  source: Dwg2DxfSource
  /** `VERSION.txt` next to the executable, else the first line of `dwg2dxf --version`; null when neither answers. */
  version: string | null
}

/** dwg2dxf could not be found; the message lists every location searched. */
export class Dwg2DxfMissingError extends Error {
  /**
   * @param searched - locations searched, in order.
   */
  constructor(readonly searched: readonly string[]) {
    super(
      `本机没有 DWG 转换器 dwg2dxf（LibreDWG），无法打开 DWG。查找顺序：\n${searched.map(s => `  - ${s}`).join('\n')}\n`
      + '处理办法：在插件配置 dwg2dxfPath 指定 dwg2dxf 可执行文件，或设置环境变量 DWG2DXF_BIN，或把官方发布的 dwg2dxf 放进插件 bin/<平台-架构>/ 目录；也可以先在 CAD 软件里另存为 DXF 再打开。',
    )
    this.name = 'Dwg2DxfMissingError'
  }
}

/** Conversion failed: non-zero exit, missing output, timeout, cancellation, or size limit. */
export class Dwg2DxfFailedError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'Dwg2DxfFailedError'
  }
}

/** Inputs to {@link resolveDwg2dxf}. */
export interface ResolveOptions {
  configPath: string | undefined
  envPath: string | undefined
  /** Package `bin/` directory. */
  bundledRoot: string
  platform: NodeJS.Platform
  arch: string
  subprocess: SubprocessRuntime
  signal: AbortSignal
}

async function isExecutable(path: string): Promise<boolean> {
  try {
    await access(path, constants.X_OK)
    return (await stat(path)).isFile()
  } catch (error) {
    // Missing or not executable: this candidate is skipped and listed in the error.
    void error
    return false
  }
}

/**
 * Locate dwg2dxf.
 * @param options - configured path, environment value, bundled root, platform, and the subprocess service.
 * @returns the executable path and where it came from (version not yet read).
 * @throws {Dwg2DxfMissingError} when no candidate exists; a configured path that does not exist also throws.
 */
export async function resolveDwg2dxf(options: ResolveOptions): Promise<Omit<Dwg2DxfBinary, 'version'>> {
  const exe = options.platform === 'win32' ? 'dwg2dxf.exe' : 'dwg2dxf'
  const searched: string[] = []
  if (options.configPath !== undefined && options.configPath !== '') {
    if (await isExecutable(options.configPath)) return { path: options.configPath, source: 'config' }
    throw new Dwg2DxfMissingError([`Config.dwg2dxfPath = ${options.configPath}（不存在或不可执行）`])
  }
  if (options.envPath !== undefined && options.envPath !== '') {
    searched.push(`DWG2DXF_BIN = ${options.envPath}`)
    if (await isExecutable(options.envPath)) return { path: options.envPath, source: 'env' }
  } else {
    searched.push('DWG2DXF_BIN（未设置）')
  }
  const bundled = join(options.bundledRoot, `${options.platform}-${options.arch}`, exe)
  searched.push(bundled)
  if (await isExecutable(bundled)) return { path: bundled, source: 'bundled' }
  searched.push('PATH 中的 dwg2dxf')
  try {
    const found = await options.subprocess.resolveExecutable('dwg2dxf', undefined, options.signal)
    return { path: found, source: 'path' }
  } catch (error) {
    if (error instanceof SubprocessExecutableNotFoundError) throw new Dwg2DxfMissingError(searched)
    throw error
  }
}

function libraryEnv(binDir: string, platform: NodeJS.Platform): NodeJS.ProcessEnv {
  if (platform === 'darwin') return { DYLD_LIBRARY_PATH: binDir }
  if (platform === 'linux') return { LD_LIBRARY_PATH: binDir }
  return {}
}

interface RunResult { exitCode: number | null; signal: NodeJS.Signals | null; stdout: string; stderr: string; timedOut: boolean }

async function run(
  subprocess: SubprocessRuntime, argv: readonly string[], cwd: string, env: NodeJS.ProcessEnv, timeoutMs: number, signal: AbortSignal,
): Promise<RunResult> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; controller.abort(new Error('dwg2dxf timeout')) }, timeoutMs)
  const forward = (): void => controller.abort(signal.reason)
  if (signal.aborted) forward()
  else signal.addEventListener('abort', forward, { once: true })
  try {
    const handle = subprocess.spawn({
      argv,
      cwd,
      stdio: { stdin: 'ignore', stdout: { maxBytes: 16 * 1024 }, stderr: { maxBytes: 16 * 1024 } },
      graceMs: 2000,
      signal: controller.signal,
      env,
    })
    const outcome = await handle.done
    if (controller.signal.aborted) await handle.waitForExit(AbortSignal.timeout(10_000))
    return {
      exitCode: outcome.exitCode,
      signal: outcome.signal,
      stdout: handle.collected.stdout?.readFrom(0).text ?? '',
      stderr: handle.collected.stderr?.readFrom(0).text ?? '',
      timedOut,
    }
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', forward)
  }
}

/**
 * Read the converter version.
 * @param bin - executable path.
 * @param subprocess - subprocess service.
 * @param signal - cancellation.
 * @returns the first line of `VERSION.txt` next to the executable, else of `dwg2dxf --version`, else null.
 */
export async function readDwg2dxfVersion(bin: string, subprocess: SubprocessRuntime, signal: AbortSignal): Promise<string | null> {
  try {
    const fromFile = (await readFile(join(dirname(bin), 'VERSION.txt'), 'utf8')).split(/\r?\n/)[0]?.trim()
    if (fromFile !== undefined && fromFile !== '') return fromFile
  } catch (error) {
    // No VERSION.txt beside the executable; ask the executable instead.
    void error
  }
  const result = await run(subprocess, [bin, '--version'], dirname(bin), libraryEnv(dirname(bin), process.platform), 10_000, signal)
  const line = `${result.stdout}\n${result.stderr}`.split(/\r?\n/).map(l => l.trim()).find(l => l !== '')
  return result.exitCode === 0 && line !== undefined ? line : null
}

/** Inputs to {@link convertDwg}. */
export interface ConvertOptions {
  bin: string
  input: string
  timeoutMs: number
  maxDxfBytes: number
  subprocess: SubprocessRuntime
  signal: AbortSignal
  /** Parent of the per-conversion temporary directory; defaults to the OS temporary directory. */
  tmpRoot?: string
}

/**
 * Convert one DWG to DXF bytes.
 * @param options - executable, input path, limits, subprocess service, and cancellation.
 * @returns the DXF bytes.
 * @throws {Dwg2DxfFailedError} on non-zero exit, missing output, timeout, cancellation, or an oversized result.
 */
export async function convertDwg(options: ConvertOptions): Promise<Buffer> {
  const dir = await mkdtemp(join(options.tmpRoot ?? tmpdir(), 'zt-cad-'))
  try {
    const input = join(dir, 'in.dwg')
    const output = join(dir, 'out.dxf')
    await copyFile(options.input, input)
    const binDir = dirname(options.bin)
    const result = await run(options.subprocess, [options.bin, '-y', '-o', output, input], binDir, libraryEnv(binDir, process.platform), options.timeoutMs, options.signal)
    if (result.timedOut) throw new Dwg2DxfFailedError(`dwg2dxf 超过 ${Math.round(options.timeoutMs / 1000)} 秒未完成，已终止。图纸可能过大或损坏；可在 CAD 软件里拆分或另存为 DXF 后再打开`)
    if (options.signal.aborted) throw new Dwg2DxfFailedError('DWG 转换已取消')
    let size: number | null = null
    try {
      size = (await stat(output)).size
    } catch (error) {
      // Missing output is reported below together with the exit status and stderr.
      void error
    }
    if (result.exitCode !== 0 || size === null) {
      const tail = result.stderr.slice(-800).trim()
      throw new Dwg2DxfFailedError(`dwg2dxf 转换失败（exit=${result.exitCode ?? result.signal}${size === null ? '，没有输出文件' : ''}）${tail !== '' ? `：\n${tail}` : ''}`)
    }
    if (size > options.maxDxfBytes) {
      throw new Dwg2DxfFailedError(`转换后的 DXF 有 ${Math.round(size / 1048576)} MB，超过单次载入上限 ${Math.round(options.maxDxfBytes / 1048576)} MB；请在 CAD 软件里拆分图纸后再打开`)
    }
    return await readFile(output)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
