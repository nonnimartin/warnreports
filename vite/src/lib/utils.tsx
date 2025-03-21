export async function fetchok(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const rep = await fetch(input, init)
  if (rep.ok) {
    return rep
  }
  const msg = `${rep.status} for ${rep.url}`
  console.error(msg, { rep })
  throw new Error(msg)
}

export function renderDate(value: string) {
  return value?.replace(/[^0-9\-]/g, '').substring(0, 10) || ''
}

export function strunc(str: string, len: number) {
  str = str || ''
  if (str?.length > len) {
    str = str.substring(0, len - 4) + ' ...'
  }
  return str
}