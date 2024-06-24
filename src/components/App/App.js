import React, { useState, useCallback, useRef, useEffect } from "react";
import { FixedSizeGrid as Grid } from "react-window";
import { useWindowSize } from "react-use";
import styled, { keyframes } from "styled-components";
import BitSet from "../../bitset";
import io from "socket.io-client";

const TOTAL_CHECKBOXES = 1000000;
const CHECKBOX_SIZE = 35; // Size of each checkbox (width and height)
const OVERSCAN_COUNT = 5; // Number of items to render outside of the visible area

const useForceUpdate = ({ bitSetRef, setCheckCount }) => {
  const [, setTick] = useState(0);
  return useCallback(() => {
    setTick((tick) => tick + 1);
    setCheckCount(bitSetRef.current.count());
  }, [bitSetRef, setCheckCount]);
};

const Checkbox = React.memo(({ index, style, isChecked, handleChange }) => {
  const backgroundColor = index % 17 === 0 ? "hsla(47, 90%, 69%, 0.7)" : null;

  return (
    <CheckboxWrapper style={style}>
      <StyledCheckbox
        type="checkbox"
        id={`checkbox-${index}`}
        checked={isChecked}
        onChange={handleChange}
      />
      <MaybeColoredDiv
        style={{ "--background-color": backgroundColor }}
      ></MaybeColoredDiv>
    </CheckboxWrapper>
  );
});

const StyledCheckbox = styled.input`
  margin: 0;
  padding: 0;
  width: 25px;
  height: 25px;
  box-shadow: none;
`;

const MaybeColoredDiv = styled.div`
  position: absolute;
  pointer-events: none;
  border: 5px solid var(--background-color);
  height: 29px;
  width: 29px;
  border-radius: 2px;
`;

const fadeIn = keyframes`
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
`;

const CheckboxWrapper = styled.div`
  display: flex;
  align-items: center;
  justify-content: center;
  width: ${CHECKBOX_SIZE}px;
  height: ${CHECKBOX_SIZE}px;
  opacity: var(--opacity);
  transition: opacity 0.5s;
  animation: ${fadeIn} 0.4s;
`;

const App = () => {
  const { width, height } = useWindowSize();
  const gridRef = useRef();
  const [jumpToIndex, setJumpToIndex] = useState("");

  const gridWidth = Math.floor(width * 0.95);
  const columnCount = Math.floor(gridWidth / CHECKBOX_SIZE);
  const rowCount = Math.ceil(TOTAL_CHECKBOXES / columnCount);
  const bitSetRef = useRef(new BitSet(TOTAL_CHECKBOXES));
  const [checkCount, setCheckCount] = React.useState(bitSetRef.current.count());
  const forceUpdate = useForceUpdate({ bitSetRef, setCheckCount });
  const [isLoading, setIsLoading] = useState(true);
  const recentlyCheckedClientSide = useRef({});

  useEffect(() => {
    const fetchInitialState = async () => {
      try {
        const response = await fetch("/api/initial-state");
        const data = await response.json();
        setCheckCount(data.count);
        data.setBits.forEach(([index, count]) => {
          for (let i = 0; i < count; i++) {
            bitSetRef.current.set(index + i);
          }
        });
        setIsLoading(false);
      } catch (error) {
        console.error("Failed to fetch initial state:", error);
        setIsLoading(false);
      }
    };

    fetchInitialState();
  }, []);

  useEffect(() => {
    const socket = io.connect();

    // Listen for bit toggle events
    socket.on("bit_toggled", (data) => {
      bitSetRef.current.makeThisValue(data.index, data.value);
      forceUpdate();
    });

    // Listen for full state updates
    socket.on("full_state", (data) => {
      console.log(`Received full state update: ${JSON.stringify(data)}`);
      console.log(
        `RECENTLY CHECKED: ${JSON.stringify(recentlyCheckedClientSide.current)}`
      );
      const newBitset = new BitSet(TOTAL_CHECKBOXES);
      const recentlyChecked = { ...recentlyCheckedClientSide.current };
      Object.entries(recentlyChecked).forEach(([index, { value, timeout }]) => {
        newBitset.makeThisValue(index, value);
      });
      data.setBits.forEach(([startingIndex, count]) => {
        for (let i = 0; i < count; i++) {
          const index = startingIndex + i;
          if (recentlyCheckedClientSide.current[index]) {
            const { value, timeout } = recentlyCheckedClientSide.current[index];
            console.log(`DROPPING UPDATE and using ${value} for ${index}`);
          } else {
            // console.log(`Setting ${index}`);
            newBitset.set(index);
          }
        }
      });
      bitSetRef.current = newBitset;
      setCheckCount(data.count);
      forceUpdate();
    });

    // Clean up the socket connection when the component unmounts
    return () => {
      socket.disconnect();
    };
  }, [forceUpdate]);

  const toggleBit = useCallback(
    async (index) => {
      try {
        bitSetRef.current.toggle(index);
        forceUpdate();
        fetch(`/api/toggle/${index}`, { method: "POST" });
      } catch (error) {
        console.error("Failed to toggle bit:", error);
      }
    },
    [forceUpdate]
  );

  const Cell = React.useCallback(
    ({ columnIndex, rowIndex, style, isLoading }) => {
      const index = rowIndex * columnCount + columnIndex;
      if (index >= TOTAL_CHECKBOXES) return null;

      const isChecked = bitSetRef.current.get(index);

      const handleChange = () => {
        toggleBit(index);

        const timeout = setTimeout(() => {
          delete recentlyCheckedClientSide.current[index];
        }, 1000);

        if (recentlyCheckedClientSide.current[index]) {
          clearTimeout(recentlyCheckedClientSide.current[index].timeout);
        }

        recentlyCheckedClientSide.current[index] = {
          value: !isChecked,
          timeout,
        };
        console.log(
          `RECENTLY CHECKED: ${JSON.stringify(recentlyCheckedClientSide.current)}`
        );
      };

      return (
        <Checkbox
          key={index}
          index={index}
          style={style}
          isChecked={isChecked}
          handleChange={handleChange}
        />
      );
    },
    [columnCount, toggleBit]
  );

  const handleJumpToCheckbox = (e) => {
    e.preventDefault();
    const index = parseInt(jumpToIndex, 10) - 1; // Subtract 1 because array is 0-indexed
    if (index >= 0 && index < TOTAL_CHECKBOXES) {
      const rowIndex = Math.floor(index / columnCount);
      const columnIndex = index % columnCount;
      gridRef.current.scrollTo({
        scrollTop: rowIndex * CHECKBOX_SIZE,
        scrollLeft: columnIndex * CHECKBOX_SIZE,
      });
    }
    setJumpToIndex("");
  };

  return (
    <Wrapper>
      <Heading style={{ "--width": columnCount * CHECKBOX_SIZE + "px" }}>
        <SiteHead>
          a website by <a href="https://eieio.games">eieio</a>
        </SiteHead>
        <Title>One Million Checkboxes</Title>
        <CountHead style={{ "--opacity": isLoading ? 0 : 1 }}>
          {checkCount} checked
        </CountHead>
        <Explanation>(checking a box checks it for everyone!)</Explanation>
      </Heading>
      <form
        onSubmit={handleJumpToCheckbox}
        style={{
          position: "fixed",
          right: "0",
          bottom: "0",
          zIndex: 1,
          margin: "5px",
        }}
      >
        <JumpInput
          type="number"
          value={jumpToIndex}
          onChange={(e) => setJumpToIndex(e.target.value)}
          placeholder="checkbox number"
          min="1"
          max={TOTAL_CHECKBOXES}
        />
        <JumpButton type="submit">Jump!</JumpButton>
      </form>
      {isLoading ? (
        <p>Loading...</p>
      ) : (
        <Grid
          className="grid"
          width={gridWidth}
          height={height} // Adjust for header and form
          columnCount={columnCount}
          columnWidth={CHECKBOX_SIZE}
          rowCount={rowCount}
          rowHeight={CHECKBOX_SIZE}
          ref={gridRef}
          overscanRowCount={OVERSCAN_COUNT}
          overscanColumnCount={OVERSCAN_COUNT}
          style={{
            width: "fit-content",
            margin: "0 auto",
            "--opacity": isLoading ? 0 : 1,
            transition: "opacity 5.5s",
          }}
        >
          {Cell}
        </Grid>
      )}
    </Wrapper>
  );
};

const Heading = styled.div`
  display: grid;
  justify-content: space-between;

  align-items: baseline;
  width: var(--width);
  margin: 10px auto 0;
  grid-template-columns: 1fr auto 1fr;
  grid-template-rows: auto auto;
  grid-template-areas:
    "site title count"
    ". sub .";

  padding-bottom: 10px;
  border-bottom: 2px solid var(--dark);

  @media (max-width: 850px) {
    grid-template-columns: 1fr auto auto 1fr;
    grid-template-rows: auto auto auto;
    grid-template-areas:
      "title title title title"
      ". sub sub ."
      "site site count count";
  }
`;

const JumpInput = styled.input`
  margin: 0;
  padding: 8px;
  height: 40px;
  font-size: 1rem;
  width: 160px;
  border: 2px solid var(--blue);
  border-radius: 0;
`;

const JumpButton = styled.button`
  margin: 0;
  padding: 8px;
  height: 40px;
  font-size: 1rem;
  background-color: var(--blue);
  border: none;
  color: white;
  cursor: pointer;
  transition: background-color 0.3s;
`;

const Title = styled.h1`
  margin: 0;
  padding: 8px 0 0 0;
  font-size: clamp(1.75rem, 2vw + 1rem, 2.5rem);
  font-family: "Sunset Demi", serif;
  text-align: center;
  grid-area: title;
`;

const SubHead = styled.h2`
  margin: 0;
  padding: 4px 0 0 0;
  flex: 1;
  font-size: clamp(1rem, 0.15vw + 1rem, 1.5rem);
  font-family: "Apercu Regular Pro", sans-serif;

  & a {
    color: var(--blue);
    text-decoration: underline;
    // dotted underline
    text-decoration-style: dashed;
    // move underline a little further down
    text-underline-offset: 0.12em;
    transition: color 0.3s;
  }

  & a:hover {
    color: var(--dark);
  }
`;

const Explanation = styled.p`
  font-size: 1rem;
  text-align: center;
  grid-area: sub;
  font-family: "Apercu Italic Pro", sans-serif;
  // italicize
  font-style: italic;
`;

const SiteHead = styled(SubHead)`
  text-align: left;
  grid-area: site;
`;

const CountHead = styled(SubHead)`
  text-align: right;
  grid-area: count;
  opacity: var(--opacity);
  transition: opacity 0.5s;
`;

const Wrapper = styled.div`
  display: flex;
  align-items: center;
  flex-direction: column;
  height: 100vh;
`;

export default App;
