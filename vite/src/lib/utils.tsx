export async function fetchok(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const rep = await fetch(input, init)
  if (rep.ok) {
    return rep
  }
  const msg = `${rep.status} for ${rep.url}`
  console.error(msg, {rep})
  throw new Error(msg)
}
