class BitSet {
  constructor(size) {
    this.size = size;
    this.bits = new Uint32Array(Math.ceil(size / 32));
    this.checkCount = 0;
  }

  set(index) {
    const arrayIndex = Math.floor(index / 32);
    const bitIndex = index % 32;
    const current = this.bits[arrayIndex];
    if ((current & (1 << bitIndex)) === 0) {
      this.bits[arrayIndex] |= 1 << bitIndex;
      this.checkCount++;
    }
  }

  clear(index) {
    const arrayIndex = Math.floor(index / 32);
    const bitIndex = index % 32;
    const current = this.bits[arrayIndex];
    if ((current & (1 << bitIndex)) === 0) {
      return;
    }
    this.bits[arrayIndex] &= ~(1 << bitIndex);
    this.checkCount--;
  }

  makeThisValue(index, value) {
    if (value) {
      this.set(index);
    } else {
      this.clear(index);
    }
  }

  get(index) {
    const arrayIndex = Math.floor(index / 32);
    const bitIndex = index % 32;
    return (this.bits[arrayIndex] & (1 << bitIndex)) !== 0;
  }

  count() {
    return this.checkCount;
  }

  toggle(index) {
    if (this.get(index)) {
      this.clear(index);
    } else {
      this.set(index);
    }
  }
}

export default BitSet;
