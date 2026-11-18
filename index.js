import { execFile } from 'node:child_process'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)
const packageRoot = fileURLToPath(new URL('.', import.meta.url))
const installer = join(packageRoot, 'scripts', 'install.sh')

/** Register DeepSeek Harness as an external Xcode ACP Agent. */
export async function apply(ctx) {
  try {
    const { stdout, stderr } = await execFileAsync('/bin/bash', [installer], {
      env: { ...process.env },
      timeout: 60_000,
      maxBuffer: 1024 * 1024,
      windowsHide: true,
    })
    if (stdout.trim()) ctx.logger.info(stdout.trim())
    if (stderr.trim()) ctx.logger.warn(stderr.trim())
    ctx.logger.info('Xcode ACP Agent is registered. Restart Xcode to use DeepSeek Harness.')
  } catch (error) {
    const detail = error?.stderr?.trim() || error?.message || String(error)
    throw new Error(`Xcode ACP setup failed: ${detail}`, { cause: error })
  }
}
